from app.models import Order, Shipment
from policies.diagnosis import diagnose


def recommended_action(order: Order, shipment: Shipment, message: str = "") -> str:
    """
    Returns one of:
    - open_investigation
    - advise_wait_then_investigate
    - reassure_and_monitor
    - verify_address
    - escalate
    """

    d = diagnose(message, shipment)

    # Returned to sender -> verify address step
    if d.label == "return_to_sender":
        return "verify_address"

    # High-value orders -> stricter handling
    if order.value is not None and float(order.value) > 300:
        # if anything risky, open investigation
        if d.label in {"delivered_not_received", "stuck_in_transit", "delayed", "damaged", "unknown"}:
            return "open_investigation"

    # Delivered not received -> checklist route (your graph decides message + escalation)
    if d.label == "delivered_not_received":
        return "advise_wait_then_investigate"

    # Damaged or attempted delivery -> needs follow-up questions / human resolution
    if d.label in {"damaged", "delivery_attempted"}:
        return "escalate"

    # Transit/Delay -> reassure & monitor
    if d.label in {"stuck_in_transit", "delayed", "in_transit"}:
        return "reassure_and_monitor"

    # Low confidence / unknown -> escalate
    return "escalate"
