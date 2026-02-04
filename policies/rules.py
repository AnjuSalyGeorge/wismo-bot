from datetime import datetime, timezone
from typing import Optional

from app.models import Order, Shipment


DELIVERED_WAIT_HOURS = 24
HIGH_VALUE_THRESHOLD = 300.0


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    # supports "2026-02-03T12:34:56Z"
    ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _hours_since(ts: Optional[str]) -> Optional[float]:
    dt = _parse_ts(ts)
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 3600.0


def _latest_delivered_ts(shipment: Shipment) -> Optional[str]:
    """
    Find the most recent delivered timestamp from the shipment timeline.
    Your TrackingEvent model uses 'ts' (not 'timestamp').
    """
    if not shipment.timeline:
        return None

    latest: Optional[str] = None
    for ev in shipment.timeline:
        status = (getattr(ev, "status", "") or "").lower().strip()
        ts = getattr(ev, "ts", None)  # ✅ your model field
        if status in {"delivered", "delivery_confirmed", "delivered_to_mailroom"} and ts:
            latest = ts
    return latest


def recommended_action(order: Order, shipment: Shipment) -> str:
    """
    Returns one of:
    - open_investigation
    - advise_wait_then_investigate
    - reassure_and_monitor
    - verify_address
    - escalate
    """
    status = (shipment.current_status or "").lower().strip()

    order_value = float(order.value) if order.value is not None else None
    is_high_value = order_value is not None and order_value > HIGH_VALUE_THRESHOLD

    # 1) Returned to sender -> verify address step
    if status in {"returned_to_sender", "return_to_sender", "rts"}:
        return "verify_address"

    # 2) Delivered logic with <24h rule
    if status in {"delivered", "delivery_confirmed", "delivered_to_mailroom"}:
        delivered_ts = _latest_delivered_ts(shipment)
        hrs = _hours_since(delivered_ts) if delivered_ts else None

        # Delivered recently (<24h): advise wait + checklist
        if hrs is not None and hrs < DELIVERED_WAIT_HOURS:
            return "advise_wait_then_investigate"

        # Delivered long ago OR timestamp missing:
        # High-value -> investigation; otherwise escalate
        if is_high_value:
            return "open_investigation"
        return "escalate"

    # 3) High value exception states -> open investigation
    if is_high_value and status in {"exception", "damaged", "lost", "unknown"}:
        return "open_investigation"

    # 4) In transit -> reassure and monitor
    if status in {"in_transit", "out_for_delivery", "label_created", "picked_up"}:
        return "reassure_and_monitor"

    # 5) Low confidence / unknown -> escalate
    return "escalate"
