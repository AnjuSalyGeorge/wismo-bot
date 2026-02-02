from app.models import Order, Shipment


def is_high_value(order: Order, threshold: float = 300.0) -> bool:
    return order.value >= threshold


def diagnose_exception(shipment: Shipment) -> str:
    if shipment.current_status == "delivered":
        return "delivered"
    if shipment.current_status == "in_transit":
        return "in_transit"
    return "unknown"


def recommended_action(order: Order, shipment: Shipment) -> str:
    ex = diagnose_exception(shipment)

    if ex == "delivered":
        return "open_investigation" if is_high_value(order) else "advise_wait_then_investigate"

    if ex == "in_transit":
        return "reassure_and_monitor"

    return "escalate"
