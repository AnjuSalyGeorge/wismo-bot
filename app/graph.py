from typing import TypedDict, List, Dict, Any, Optional

from langgraph.graph import StateGraph, END

from tools.orders import get_order
from tools.tracking import get_tracking
from tools.cases import create_case, count_recent_claims_by_email
from tools.logs import log_action

from policies.rules import recommended_action
from policies.diagnosis import diagnose

from llm.client import infer_intent
from app.models import Order, Shipment


# Repeat-claims escalation applies only for these diagnosis labels
REPEAT_CLAIM_LABELS = {"delivered_not_received"}
REPEAT_CLAIM_THRESHOLD = 2  # 3rd+ within 60 days triggers escalation


class GraphState(TypedDict, total=False):
    # input
    message: str
    order_id: Optional[str]
    email: Optional[str]
    session_id: str

    # internal
    llm_intent: Dict[str, Any]
    diagnosis: Dict[str, Any]

    # outputs
    actions: List[Dict[str, Any]]
    reply: str
    case_id: Optional[str]

    # tool data
    order: Dict[str, Any]
    shipment: Dict[str, Any]


def intake_node(state: GraphState) -> GraphState:
    state.setdefault("actions", [])
    state.setdefault("reply", "")
    state.setdefault("case_id", None)
    return state


def understand_node(state: GraphState) -> GraphState:
    """
    Day 6: LLM understands the message and outputs strict JSON:
    - intent
    - extracted_order_id/email
    - missing_fields
    """
    sid = state.get("session_id", "unknown")
    msg = state.get("message", "") or ""

    out = infer_intent(msg)

    # Save a minimal JSON payload into state (serializable)
    payload = {
        "intent": out.intent,
        "extracted_order_id": out.extracted_order_id,
        "extracted_email": out.extracted_email,
        "missing_fields": out.missing_fields,
        "risk_flags": out.risk_flags,
        "confidence": out.confidence,
        "suggested_next_action": out.suggested_next_action,
    }

    state["llm_intent"] = payload
    log_action(sid, "llm_intent", payload)
    state["actions"].append({"llm_intent": {"intent": out.intent, "missing_fields": out.missing_fields, "confidence": out.confidence}})

    # ✅ If the user didn't provide order_id/email in request body,
    # but LLM extracted them from the message, fill them.
    if not state.get("order_id") and out.extracted_order_id:
        state["order_id"] = out.extracted_order_id
    if not state.get("email") and out.extracted_email:
        state["email"] = out.extracted_email

    # ✅ If still missing fields, ask follow-up and STOP (do not retrieve)
    still_missing = []
    if not state.get("order_id"):
        still_missing.append("order_id")
    if not state.get("email"):
        still_missing.append("email")

    if still_missing:
        state["reply"] = (
            "To help you, I need a couple details:\n"
            "1) Your order ID (example: A1004)\n"
            "2) The email used for the order\n"
        )
        return state

    return state


def retrieve_node(state: GraphState) -> GraphState:
    state.setdefault("actions", [])
    sid = state.get("session_id", "unknown")

    # If understand_node already asked a question, stop
    if state.get("reply"):
        return state

    try:
        order = get_order(state["order_id"], state["email"])
        log_action(sid, "tool_call", {"tool": "get_order", "order_id": order.order_id})
        state["actions"].append({"tool": "get_order", "order_id": order.order_id})

        shipment = get_tracking(order.tracking_id)
        log_action(sid, "tool_call", {"tool": "get_tracking", "tracking_id": shipment.tracking_id})
        state["actions"].append({"tool": "get_tracking", "tracking_id": shipment.tracking_id})

        state["order"] = order.model_dump()
        state["shipment"] = shipment.model_dump()
        return state

    except PermissionError as e:
        log_action(sid, "error", {"where": "retrieve_node", "error": str(e)})
        state["reply"] = "That email doesn’t match the order on file. Please double-check and try again."
        return state

    except ValueError as e:
        log_action(sid, "error", {"where": "retrieve_node", "error": str(e)})
        state["reply"] = "I couldn’t find that order/tracking. Please confirm your order ID and email."
        return state

    except Exception as e:
        log_action(sid, "error", {"where": "retrieve_node", "error": repr(e)})
        state["reply"] = "Something went wrong while looking up your order. Please try again."
        return state


def decide_node(state: GraphState) -> GraphState:
    state.setdefault("actions", [])
    sid = state.get("session_id", "unknown")

    # If earlier node already produced a reply, stop
    if state.get("reply"):
        return state

    if not state.get("order") or not state.get("shipment"):
        state["reply"] = "I couldn’t retrieve your order details. Please try again."
        return state

    order = Order(**state["order"])
    shipment = Shipment(**state["shipment"])
    message = state.get("message", "") or ""

    # Day 5 diagnosis
    diag = diagnose(message, shipment)
    log_action(sid, "diagnosis", {"label": diag.label, "confidence": diag.confidence, "notes": diag.notes})
    state["diagnosis"] = {"label": diag.label, "confidence": diag.confidence}
    state["actions"].append({"diagnosis": {"label": diag.label, "confidence": diag.confidence}})

    # Policy decision
    action = recommended_action(order, shipment, message=message)

    # Repeat claims override ONLY for delivered_not_received
    if diag.label in REPEAT_CLAIM_LABELS and getattr(order, "email", None):
        try:
            recent_claims = count_recent_claims_by_email(order.email, days=60)
            log_action(sid, "policy_check", {"rule": "repeat_claims_60d", "email": order.email, "count": recent_claims})
            if recent_claims > REPEAT_CLAIM_THRESHOLD:
                action = "escalate"
                log_action(sid, "policy_override", {"rule": "repeat_claims_60d", "forced_action": "escalate"})
        except Exception as e:
            log_action(sid, "error", {"where": "repeat_claim_check", "error": repr(e)})

    log_action(sid, "decision", {"decision": action})
    state["actions"].append({"decision": action})

    # Follow-up questions (Day 5)
    if diag.label == "delivery_attempted":
        state["reply"] = (
            "It looks like a delivery was attempted.\n"
            "Quick questions:\n"
            "1) Unit/apt/buzzer or gate code?\n"
            "2) Best phone number for the courier?\n"
            "3) Prefer re-delivery or pickup?"
        )
        return state

    if diag.label == "damaged":
        state["reply"] = (
            "Sorry about that — it looks like the package may be damaged.\n"
            "Please confirm:\n"
            "1) Outer box damaged, item damaged, or both?\n"
            "2) Prefer replacement or refund?\n"
            "If you have a photo, you can upload it too."
        )
        return state

    if action == "verify_address":
        state["reply"] = (
            "Your package was returned to sender. Let’s confirm your shipping address so we can resend it.\n"
            "Please reply with:\n"
            "1) Full address (street, city, province, postal code)\n"
            "2) Unit/apt/buzzer number (if any)\n"
            "3) Preferred phone number for the courier\n"
        )
        return state

    if action == "open_investigation":
        case_id = create_case(order.order_id, reason="shipping_exception", user_message=message, email=order.email)
        log_action(sid, "tool_call", {"tool": "create_case", "case_id": case_id})
        state["case_id"] = case_id
        state["actions"].append({"tool": "create_case", "case_id": case_id})
        state["reply"] = f"I opened an investigation ({case_id}). A support agent will review and follow up."
        return state

    if action == "escalate":
        case_id = create_case(order.order_id, reason="escalate", user_message=message or "escalation requested", email=order.email)
        log_action(sid, "tool_call", {"tool": "create_case", "case_id": case_id})
        state["case_id"] = case_id
        state["actions"].append({"tool": "create_case", "case_id": case_id})
        state["reply"] = f"I’m escalating this to a human support agent. I created a case ({case_id}). A support agent will follow up."
        return state

    if action == "advise_wait_then_investigate":
        state["reply"] = (
            "It’s marked delivered recently. Here’s a quick checklist:\n"
            "• Check mailbox/porch/garage and side doors\n"
            "• Check with neighbors/household\n"
            "• If apartment/condo: check mailroom/concierge/lockers\n"
            "• Look for a carrier photo/note (if available)\n\n"
            "If you still can’t find it after 24 hours, reply here and I’ll open an investigation."
        )
        return state

    if action == "reassure_and_monitor":
        state["reply"] = "Your shipment is in transit. If it doesn’t move for 48 hours, I can open a carrier investigation."
        return state

    state["reply"] = "I’m not fully sure what’s happening. I can escalate this to a human support agent."
    return state


def build_graph():
    g = StateGraph(GraphState)

    g.add_node("intake", intake_node)
    g.add_node("understand", understand_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("decide", decide_node)

    g.set_entry_point("intake")
    g.add_edge("intake", "understand")
    g.add_edge("understand", "retrieve")
    g.add_edge("retrieve", "decide")
    g.add_edge("decide", END)

    return g.compile()
