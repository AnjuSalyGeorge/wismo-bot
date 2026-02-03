from app.models import Shipment, TrackingEvent
from app.config import get_firestore_client


def get_tracking(tracking_id: str) -> Shipment:
    db = get_firestore_client()
    doc = db.collection("shipments").document(tracking_id).get()

    if not doc.exists:
        raise ValueError("Tracking not found.")

    data = doc.to_dict() or {}
    timeline_raw = data.get("timeline", []) or []

    timeline = [
        TrackingEvent(
            ts=e.get("ts", ""),
            status=e.get("status", ""),
            location=e.get("location"),
        )
        for e in timeline_raw
    ]

    return Shipment(
        tracking_id=data["tracking_id"],
        carrier=data.get("carrier", "unknown"),
        current_status=data.get("current_status", "unknown"),
        timeline=timeline,
    )
