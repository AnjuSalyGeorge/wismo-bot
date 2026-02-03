from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END

from tools.orders import get_order
from tools.tracking import get_tracking
from tools.cases import create_case
from policies.rules import recommended_action
from app.models import Order, Shipment
from tools.logs import log_action


class GraphState(TypedDict, total=False):
    message: str
    order_id: Optional[str]
    email: Optional[str]
    actions: List[Dict[str, Any]]
    reply: str
    case_id: Optional[str]
    order: Dict[str, Any]
    shipment: Dict[str, Any]
    session_id: str


def intake_node(state: GraphState) -> GraphState:
    # Ensure actions list exists
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

    # If retrieve failed, reply already set
    if not state.get("order") or not state.get("shipment"):
        return state

    order = Order(**state["order"])
    shipment = Shipment(**state["shipment"])

    action = recommended_action(order, shipment)
    log_action(sid, "decision", {"decision": action})
    state["actions"].append({"decision": action})

    # ✅ Create a case when we open investigation / advise wait-then-investigate
    if action in ("open_investigation", "advise_wait_then_investigate"):
        case_id = create_case(
            order.order_id,
            reason="shipping_exception",
            user_message=state.get("message", ""),
        )
        log_action(sid, "tool_call", {"tool": "create_case", "case_id": case_id})
        state["case_id"] = case_id
        state["actions"].append({"tool": "create_case", "case_id": case_id})

    # ✅ NEW: Create a case for "escalate" too (this is what you were missing)
    if action == "escalate":
        case_id = create_case(
            order.order_id,
            reason="escalate",
            user_message=state.get("message", "escalation requested"),
        )
        log_action(sid, "tool_call", {"tool": "create_case", "case_id": case_id})
        state["case_id"] = case_id
        state["actions"].append({"tool": "create_case", "case_id": case_id})

        state["reply"] = (
            f"I’m escalating this to a human support agent. "
            f"I created a case ({case_id}). A support agent will follow up."
        )
        return state

    # Replies for other actions
    if action == "open_investigation":
        state["reply"] = (
            f"I see your package is marked delivered. Because this is a higher-value order, "
            f"I opened an investigation ({state.get('case_id')}). A support agent will review and follow up."
        )
    elif action == "advise_wait_then_investigate":
        state["reply"] = (
            "It’s marked delivered. Please check your mailbox/porch, neighbors, and building reception. "
            "If it doesn’t show up within 24 hours, I can open an investigation."
        )
    elif action == "reassure_and_monitor":
        state["reply"] = (
            "Your shipment is in transit. If it doesn’t move for 48 hours, "
            "I can open a carrier investigation."
        )
    else:
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
