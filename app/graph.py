from typing import TypedDict, List, Dict, Any, Optional

from langgraph.graph import StateGraph, END

from tools.orders import get_order
from tools.tracking import get_tracking
from tools.cases import create_case, count_recent_claims_by_email
from tools.logs import log_action
from tools.sessions import (
    get_session,
    update_session,
    append_message,
    get_active_case_id,
    set_active_case_id,
)

from policies.rules import recommended_action
from policies.diagnosis import diagnose

from llm.client import infer_intent, generate_handoff
from app.models import Order, Shipment


REPEAT_CLAIM_LABELS = {"delivered_not_received"}
REPEAT_CLAIM_THRESHOLD = 2  # 3rd+ within 60 days triggers escalation


class GraphState(TypedDict, total=False):
    message: str
    order_id: Optional[str]
    email: Optional[str]
    session_id: str

    session: Dict[str, Any]

    llm_intent: Dict[str, Any]
    diagnosis: Dict[str, Any]

    actions: List[Dict[str, Any]]
    reply: str
    case_id: Optional[str]

    order: Dict[str, Any]
    shipment: Dict[str, Any]


def _is_details_only_message(msg: str, out) -> bool:
    """
    If the user is mostly just sending missing fields (order/email),
    reuse prior intent and complaint from session to avoid LLM drift.
    """
    m = (msg or "").strip().lower()

    complaint_keywords = [
        "not received", "did not receive", "didn't receive",
        "delivered but", "stuck", "not moving", "delayed",
        "attempt", "attempted", "damaged", "broken", "return", "returned",
        "lost", "missing",
    ]
    if any(k in m for k in complaint_keywords):
        return False

    has_emailish = ("@" in m and "." in m)
    has_orderish = ("order" in m) or any(ch.isdigit() for ch in m)

    looks_like_details = (out.intent == "track_order") and (out.extracted_order_id or out.extracted_email)
    return looks_like_details and (has_orderish or has_emailish)


def intake_node(state: GraphState) -> GraphState:
    state.setdefault("actions", [])
    state.setdefault("reply", "")
    state.setdefault("case_id", None)

    sid = state.get("session_id") or "unknown"

    try:
        state["session"] = get_session(sid)
    except Exception as e:
        log_action(sid, "error", {"where": "intake_node:get_session", "error": repr(e)})
        state["session"] = {}

    msg = state.get("message", "") or ""
    try:
        append_message(sid, "user", msg)
    except Exception as e:
        log_action(sid, "error", {"where": "intake_node:append_message", "error": repr(e)})

    return state


def understand_node(state: GraphState) -> GraphState:
    sid = state.get("session_id", "unknown")
    msg = state.get("message", "") or ""
    sess = state.get("session") or {}

    out = infer_intent(msg)
    details_only = _is_details_only_message(msg, out)

    intent = out.intent
    if details_only and sess.get("last_intent"):
        intent = sess["last_intent"]

    payload = {
        "intent": intent,
        "extracted_order_id": out.extracted_order_id,
        "extracted_email": out.extracted_email,
        "missing_fields": out.missing_fields,
        "risk_flags": out.risk_flags,
        "confidence": out.confidence,
        "suggested_next_action": out.suggested_next_action,
    }

    state["llm_intent"] = payload
    log_action(sid, "llm_intent", payload)

    state["actions"].append(
        {"llm_intent": {"intent": intent, "missing_fields": out.missing_fields, "confidence": out.confidence}}
    )

    # Fill order/email:
    # 1) request body
    # 2) LLM extracted
    # 3) session memory
    if not state.get("order_id") and out.extracted_order_id:
        state["order_id"] = out.extracted_order_id
    if not state.get("email") and out.extracted_email:
        state["email"] = out.extracted_email

    if not state.get("order_id") and sess.get("order_id"):
        state["order_id"] = sess["order_id"]
    if not state.get("email") and sess.get("email"):
        state["email"] = sess["email"]

    patch: Dict[str, Any] = {
        "order_id": state.get("order_id"),
        "email": state.get("email"),
        "last_intent": intent,
    }
    if not details_only:
        patch["last_complaint"] = msg

    try:
        update_session(sid, patch)
    except Exception as e:
        log_action(sid, "error", {"where": "understand_node:update_session", "error": repr(e)})

    still_missing: List[str] = []
    if not state.get("order_id"):
        still_missing.append("order_id")
    if not state.get("email"):
        still_missing.append("email")

    if still_missing:
        question = (
            "To help you, I need a couple details:\n"
            "1) Your order ID (example: A1004)\n"
            "2) The email used for the order\n"
        )
        state["reply"] = question

        try:
            update_session(sid, {"last_question": question, "missing_fields": still_missing})
            append_message(sid, "assistant", question)
        except Exception as e:
            log_action(sid, "error", {"where": "understand_node:store_followup", "error": repr(e)})

        return state

    return state


def retrieve_node(state: GraphState) -> GraphState:
    sid = state.get("session_id", "unknown")

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

        # Save confirmed order/email into session
        try:
            update_session(sid, {"order_id": order.order_id, "email": order.email})
        except Exception as e:
            log_action(sid, "error", {"where": "retrieve_node:update_session", "error": repr(e)})

        return state

    except PermissionError as e:
        log_action(sid, "error", {"where": "retrieve_node", "error": str(e)})
        state["reply"] = "That email doesn’t match the order on file. Please double-check and try again."
        try:
            append_message(sid, "assistant", state["reply"])
        except Exception:
            pass
        return state

    except ValueError as e:
        log_action(sid, "error", {"where": "retrieve_node", "error": str(e)})
        state["reply"] = "I couldn’t find that order/tracking. Please confirm your order ID and email."
        try:
            append_message(sid, "assistant", state["reply"])
        except Exception:
            pass
        return state

    except Exception as e:
        log_action(sid, "error", {"where": "retrieve_node", "error": repr(e)})
        state["reply"] = "Something went wrong while looking up your order. Please try again."
        try:
            append_message(sid, "assistant", state["reply"])
        except Exception:
            pass
        return state


def _get_effective_message(state: GraphState) -> str:
    sess = state.get("session") or {}
    raw_message = state.get("message", "") or ""
    if sess.get("last_complaint"):
        # If this looks like a details-only message, reuse last complaint for diagnosis/policy
        if len(raw_message.strip()) < 80 or ("@" in raw_message) or ("order" in raw_message.lower()):
            return sess["last_complaint"]
    return raw_message


def decide_node(state: GraphState) -> GraphState:
    sid = state.get("session_id", "unknown")

    if state.get("reply"):
        return state

    if not state.get("order") or not state.get("shipment"):
        state["reply"] = "I couldn’t retrieve your order details. Please try again."
        try:
            append_message(sid, "assistant", state["reply"])
        except Exception:
            pass
        return state

    order = Order(**state["order"])
    shipment = Shipment(**state["shipment"])

    effective_message = _get_effective_message(state)

    diag = diagnose(effective_message, shipment)
    log_action(sid, "diagnosis", {"label": diag.label, "confidence": diag.confidence, "notes": diag.notes})
    state["diagnosis"] = {"label": diag.label, "confidence": diag.confidence}
    state["actions"].append({"diagnosis": {"label": diag.label, "confidence": diag.confidence}})

    action = recommended_action(order, shipment, message=effective_message)

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

    # Follow-up questions (your existing ones)
    if diag.label == "delivery_attempted":
        state["reply"] = (
            "It looks like a delivery was attempted.\n"
            "Quick questions:\n"
            "1) Unit/apt/buzzer or gate code?\n"
            "2) Best phone number for the courier?\n"
            "3) Prefer re-delivery or pickup?"
        )
        try:
            append_message(sid, "assistant", state["reply"])
            update_session(sid, {"last_question": state["reply"]})
        except Exception:
            pass
        return state

    if diag.label == "damaged":
        state["reply"] = (
            "Sorry about that — it looks like the package may be damaged.\n"
            "Please confirm:\n"
            "1) Outer box damaged, item damaged, or both?\n"
            "2) Prefer replacement or refund?\n"
            "If you have a photo, you can upload it too."
        )
        try:
            append_message(sid, "assistant", state["reply"])
            update_session(sid, {"last_question": state["reply"]})
        except Exception:
            pass
        return state

    if action == "verify_address":
        state["reply"] = (
            "Your package was returned to sender. Let’s confirm your shipping address so we can resend it.\n"
            "Please reply with:\n"
            "1) Full address (street, city, province, postal code)\n"
            "2) Unit/apt/buzzer number (if any)\n"
            "3) Preferred phone number for the courier\n"
        )
        try:
            append_message(sid, "assistant", state["reply"])
            update_session(sid, {"last_question": state["reply"]})
        except Exception:
            pass
        return state

    # -------------------------
    # ✅ Case creation + reuse
    # -------------------------
    if action in {"open_investigation", "escalate"}:
        existing_case_id = None
        try:
            existing_case_id = get_active_case_id(sid)
        except Exception as e:
            log_action(sid, "error", {"where": "decide_node:get_active_case_id", "error": repr(e)})

        # Generate handoff note (always useful, even if reusing)
        handoff = generate_handoff(
            {
                "order_id": order.order_id,
                "email": order.email,
                "status": shipment.current_status,
                "message": effective_message,
                "diagnosis": diag.label,
                "decision": action,
                "case_id": existing_case_id or "NEW",
            }
        )

        if existing_case_id:
            # Reuse the case
            state["case_id"] = existing_case_id
            state["actions"].append(
                {"tool": "reuse_case", "case_id": existing_case_id, "handoff_note": handoff}
            )
            log_action(sid, "case_reuse", {"case_id": existing_case_id})

            state["reply"] = (
                f"I’m escalating this to a human support agent. "
                f"I already have an open case ({existing_case_id}) for this session. "
                f"A support agent will follow up."
            )
            try:
                append_message(sid, "assistant", state["reply"])
            except Exception:
                pass
            return state

        # Create a new case and store in session
        reason = "shipping_exception" if action == "open_investigation" else "escalate"

        case_id = create_case(
            order.order_id,
            reason=reason,
            user_message=effective_message or "escalation requested",
            email=order.email,
            handoff_note=handoff,     # ✅ stored in Firestore case doc
            session_id=sid,           # ✅ stored in Firestore case doc
        )

        try:
            set_active_case_id(sid, case_id)
        except Exception as e:
            log_action(sid, "error", {"where": "decide_node:set_active_case_id", "error": repr(e)})

        log_action(sid, "tool_call", {"tool": "create_case", "case_id": case_id})
        state["case_id"] = case_id
        state["actions"].append({"tool": "create_case", "case_id": case_id, "handoff_note": handoff})

        if action == "open_investigation":
            state["reply"] = f"I opened an investigation ({case_id}). A support agent will review and follow up."
        else:
            state["reply"] = (
                f"I’m escalating this to a human support agent. "
                f"I created a case ({case_id}). A support agent will follow up."
            )

        try:
            append_message(sid, "assistant", state["reply"])
        except Exception:
            pass
        return state

    # Non-case paths
    if action == "advise_wait_then_investigate":
        state["reply"] = (
            "It’s marked delivered recently. Here’s a quick checklist:\n"
            "• Check mailbox/porch/garage and side doors\n"
            "• Check with neighbors/household\n"
            "• If apartment/condo: check mailroom/concierge/lockers\n"
            "• Look for a carrier photo/note (if available)\n\n"
            "If you still can’t find it after 24 hours, reply here and I’ll open an investigation."
        )
        try:
            append_message(sid, "assistant", state["reply"])
        except Exception:
            pass
        return state

    if action == "reassure_and_monitor":
        state["reply"] = "Your shipment is in transit. If it doesn’t move for 48 hours, I can open a carrier investigation."
        try:
            append_message(sid, "assistant", state["reply"])
        except Exception:
            pass
        return state

    state["reply"] = "I’m not fully sure what’s happening. I can escalate this to a human support agent."
    try:
        append_message(sid, "assistant", state["reply"])
    except Exception:
        pass
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
