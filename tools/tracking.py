from app.models import Shipment, TrackingEvent

MOCK_SHIPMENTS = {
    "T9001": Shipment(
        tracking_id="T9001",
        carrier="MockCarrier",
        current_status="in_transit",
        timeline=[
            TrackingEvent(ts="2026-01-28T10:00:00Z", status="label_created", location="Toronto"),
            TrackingEvent(ts="2026-01-29T09:00:00Z", status="picked_up", location="Toronto"),
            TrackingEvent(ts="2026-01-31T18:00:00Z", status="in_transit", location="Mississauga"),
        ],
    ),
    "T9002": Shipment(
        tracking_id="T9002",
        carrier="MockCarrier",
        current_status="delivered",
        timeline=[
            TrackingEvent(ts="2026-01-25T11:00:00Z", status="picked_up", location="Toronto"),
            TrackingEvent(ts="2026-01-27T09:30:00Z", status="out_for_delivery", location="Windsor"),
            TrackingEvent(ts="2026-01-27T15:10:00Z", status="delivered", location="Windsor"),
        ],
    ),
}


def get_tracking(tracking_id: str) -> Shipment:
    shipment = MOCK_SHIPMENTS.get(tracking_id)
    if not shipment:
        raise ValueError("Tracking not found.")
    return shipment
