from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END

from tools.orders import get_order
from tools.tracking import get_tracking
from tools.cases import create_case
from policies.rules import recommended_action
from app.models import Order, Shipment


class GraphState(TypedDict, total=False):
    message: str
    order_id: Optional[str]
    email: Optional[str]
    actions: List[Dict[str, Any]]
    reply: str
    case_id: Optional[str]
    order: Dict[str, Any]
    shipment: Dict[str, Any]


def intake_node(state: GraphState) -> GraphState:
    if not state.get("order_id") or not state.get("email"):
        state["reply"] = "Please share your order ID and the email used for the order (example: A1001, anju@example.com)."
        return state
    return state


def retrieve_node(state: GraphState) -> GraphState:
    order = get_order(state["order_id"], state["email"])
    shipment = get_tracking(order.tracking_id)

    state["actions"].append({"tool": "get_order", "order_id": order.order_id})
    state["actions"].append({"tool": "get_tracking", "tracking_id": shipment.tracking_id})

    state["order"] = order.model_dump()
    state["shipment"] = shipment.model_dump()
    return state


def decide_node(state: GraphState) -> GraphState:
    order = Order(**state["order"])
    shipment = Shipment(**state["shipment"])

    action = recommended_action(order, shipment)
    state["actions"].append({"decision": action})

    if action in ("open_investigation", "advise_wait_then_investigate"):
        case_id = create_case(order.order_id, reason="shipping_exception", user_message=state["message"])
        state["case_id"] = case_id
        state["actions"].append({"tool": "create_case", "case_id": case_id})

    if action == "open_investigation":
        state["reply"] = (
            f"I see your package is marked delivered. Because this is a higher-value order, "
            f"I opened an investigation ({state['case_id']}). A support agent will review and follow up."
        )
    elif action == "advise_wait_then_investigate":
        state["reply"] = (
            "It’s marked delivered. Please check your mailbox/porch, neighbors, and building reception. "
            "If it doesn’t show up within 24 hours, I can open an investigation."
        )
    elif action == "reassure_and_monitor":
        state["reply"] = "Your shipment is in transit. If it doesn’t move for 48 hours, I can open a carrier investigation."
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
