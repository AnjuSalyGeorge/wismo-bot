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

    if d.label == "return_to_sender":
        return "verify_address"

    if order.value is not None and float(order.value) > 300:
        if d.label in {"delivered_not_received", "stuck_in_transit", "delayed", "damaged", "unknown"}:
            return "open_investigation"

    if d.label == "delivered_not_received":
        return "advise_wait_then_investigate"

    if d.label in {"damaged", "delivery_attempted"}:
        return "escalate"

    if d.label in {"stuck_in_transit", "delayed", "in_transit"}:
        return "reassure_and_monitor"

    return "escalate"

