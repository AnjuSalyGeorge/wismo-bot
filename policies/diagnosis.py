from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List

from app.models import Shipment, TrackingEvent


@dataclass
class Diagnosis:
    label: str
    confidence: float
    notes: str = ""


DELIVERED_STATUSES = {"delivered", "delivery_confirmed", "delivered_to_mailroom"}
RTS_STATUSES = {"returned_to_sender", "return_to_sender", "rts"}
ATTEMPT_STATUSES = {"delivery_attempted", "attempted", "attempted_delivery", "notice_left"}
DAMAGED_STATUSES = {"damaged", "damage_reported"}
DELAY_STATUSES = {"delayed", "delay", "exception", "weather_delay"}


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _last_event_ts(timeline: List[TrackingEvent]) -> Optional[datetime]:
    if not timeline:
        return None
    dts = [_parse_ts(e.ts) for e in timeline if getattr(e, "ts", None)]
    dts = [d for d in dts if d is not None]
    return max(dts) if dts else None


def _hours_since(dt: Optional[datetime]) -> Optional[float]:
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 3600.0


def diagnose(message: str, shipment: Shipment) -> Diagnosis:
    msg = (message or "").lower().strip()
    status = (shipment.current_status or "").lower().strip()

    if status in RTS_STATUSES:
        return Diagnosis("return_to_sender", 0.95, "tracking status indicates RTS")

    if status in DAMAGED_STATUSES or "damag" in msg:
        return Diagnosis("damaged", 0.85, "damage keyword/status detected")

    if status in ATTEMPT_STATUSES or ("attempt" in msg or "not home" in msg):
        return Diagnosis("delivery_attempted", 0.80, "attempt keyword/status detected")

    if status in DELIVERED_STATUSES:
        if any(k in msg for k in ["not received", "did not receive", "missing", "stolen"]):
            return Diagnosis("delivered_not_received", 0.85, "delivered + not received")
        return Diagnosis("delivered", 0.70, "delivered status")

    if status in DELAY_STATUSES or "delay" in msg:
        return Diagnosis("delayed", 0.70)

    if status in {"in_transit", "out_for_delivery", "picked_up"}:
        last_dt = _last_event_ts(shipment.timeline or [])
        hrs = _hours_since(last_dt)
        if hrs and hrs >= 48:
            return Diagnosis("stuck_in_transit", 0.75)
        return Diagnosis("in_transit", 0.60)

    return Diagnosis("unknown", 0.40)
