from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END

from tools.orders import get_order
from tools.tracking import get_tracking
from tools.cases import create_case, count_recent_claims_by_email
from tools.logs import log_action

from policies.rules import recommended_action
from policies.diagnosis import diagnose
from app.models import Order, Shipment


# Only apply repeat-claims escalation for these diagnosis labels
REPEAT_CLAIM_LABELS = {"delivered_not_received"}
REPEAT_CLAIM_THRESHOLD = 2  # N; 3rd+ within 60 days triggers escalation


class GraphState(TypedDict, total=False):
    message: str
    order_id: Optional[str]
    email: Optional[str]
    session_id: str

    actions: List[Dict[str, Any]]
    reply: str
    case_id: Optional[str]

    order: Dict[str, Any]
    shipment: Dict[str, Any]

    # ✅ add diagnosis to state so other logic can read it
    diagnosis: Dict[str, Any]


def intake_node(state: GraphState) -> GraphState:
    state.setdefault("actions", [])
    if not state.get("order_id") or not state.get("email"):
        state["reply"] = (
            "Please share your order ID and the email used for the order "
            "(example: A1001, anju@example.com)."
        )
        return state
    return state


def retrieve_node(state: GraphState) -> GraphState:
    state.setdefault("actions", [])
    sid = state.get("session_id", "unknown")

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

    if not state.get("order") or not state.get("shipment"):
        return state

    order = Order(**state["order"])
    shipment = Shipment(**state["shipment"])
    message = state.get("message", "")

    # --- Day 5: Diagnosis (messy real-world interpretation) ---
    diag = diagnose(message, shipment)
    diag_payload = {"label": diag.label, "confidence": diag.confidence, "notes": diag.notes}

    log_action(sid, "diagnosis", diag_payload)
    state["diagnosis"] = {"label": diag.label, "confidence": diag.confidence}
    state["actions"].append({"diagnosis": {"label": diag.label, "confidence": diag.confidence}})

    # --- Base policy decision (rules.py) ---
    action = recommended_action(order, shipment, message=message)

    # --- Day 4: Repeat-claims override (ONLY for delivered_not_received) ---
    # ✅ This fixes your "stuck in transit" incorrectly escalating.
    if diag.label in REPEAT_CLAIM_LABELS and getattr(order, "email", None):
        try:
            recent_claims = count_recent_claims_by_email(order.email, days=60)
            log_action(
                sid,
                "policy_check",
                {"rule": "repeat_claims_60d", "email": order.email, "count": recent_claims},
            )
            if recent_claims > REPEAT_CLAIM_THRESHOLD:
                action = "escalate"
                log_action(
                    sid,
                    "policy_override",
                    {"rule": "repeat_claims_60d", "forced_action": "escalate"},
                )
        except Exception as e:
            log_action(sid, "error", {"where": "repeat_claim_check", "error": repr(e)})

    # Log FINAL decision
    log_action(sid, "decision", {"decision": action})
    state["actions"].append({"decision": action})

    # --- Day 5: Follow-up questions (ask only when needed) ---
    if diag.label == "delivery_attempted":
        state["reply"] = (
            "It looks like a delivery was attempted.\n"
            "Quick questions so we can resolve this:\n"
            "1) Is there a unit/apt/buzzer code or gate access?\n"
            "2) What’s the best phone number for the courier?\n"
            "3) Do you prefer re-delivery or pickup at a nearby location?"
        )
        return state

    if diag.label == "damaged":
        state["reply"] = (
            "Sorry about that — it looks like the package may be damaged.\n"
            "Please confirm:\n"
            "1) Is the outer box damaged, the item damaged, or both?\n"
            "2) Do you prefer a replacement or a refund?\n"
            "If you have a photo, you can upload it too."
        )
        return state

    # Returned to sender: verify address step (no case yet)
    if action == "verify_address":
        state["reply"] = (
            "Your package was returned to sender. Let’s confirm your shipping address so we can resend it.\n"
            "Please reply with:\n"
            "1) Full address (street, city, province, postal code)\n"
            "2) Unit/apt/buzzer number (if any)\n"
            "3) Preferred phone number for the courier\n"
            "Once confirmed, I can escalate for a reshipment."
        )
        return state

    # Create a case ONLY for open_investigation (high-value / high-risk)
    if action == "open_investigation":
        case_id = create_case(
            order.order_id,
            reason="shipping_exception",
            user_message=message,
            email=order.email,
        )
        log_action(sid, "tool_call", {"tool": "create_case", "case_id": case_id})
        state["case_id"] = case_id
        state["actions"].append({"tool": "create_case", "case_id": case_id})

        state["reply"] = (
            f"I opened an investigation ({case_id}). A support agent will review and follow up."
        )
        return state

    # Escalate creates a case
    if action == "escalate":
        case_id = create_case(
            order.order_id,
            reason="escalate",
            user_message=message or "escalation requested",
            email=order.email,
        )
        log_action(sid, "tool_call", {"tool": "create_case", "case_id": case_id})
        state["case_id"] = case_id
        state["actions"].append({"tool": "create_case", "case_id": case_id})

        state["reply"] = (
            f"I’m escalating this to a human support agent. "
            f"I created a case ({case_id}). A support agent will follow up."
        )
        return state

    # Delivered checklist path (no case)
    if action == "advise_wait_then_investigate":
        state["reply"] = (
            "It’s marked delivered recently. Here’s a quick checklist:\n"
            "• Check mailbox/porch/garage and any side doors\n"
            "• Check with neighbors/household members\n"
            "• If you’re in an apartment/condo: check mailroom, concierge, parcel lockers\n"
            "• Look for a carrier photo or delivery note (if available)\n\n"
            "If you still can’t find it after 24 hours, reply here and I’ll open an investigation."
        )
        return state

    # In transit / delayed
    if action == "reassure_and_monitor":
        state["reply"] = (
            "Your shipment is in transit. If it doesn’t move for 48 hours, "
            "I can open a carrier investigation."
        )
        return state

    # Fallback
    state["reply"] = "I’m not fully sure what’s happening. I can escalate this to a human support agent."
    return state


def build_graph():
    g = StateGraph(GraphState)

    g.add_node("intake", intake_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("decide", decide_node)

    g.set_entry_point("intake")
    g.add_edge("intake", "retrieve")
    g.add_edge("retrieve", "decide")
    g.add_edge("decide", END)

    return g.compile()
