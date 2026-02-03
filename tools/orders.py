from app.models import Order
from app.config import get_firestore_client


def get_order(order_id: str, email: str) -> Order:
    db = get_firestore_client()
    doc = db.collection("orders").document(order_id).get()

    if not doc.exists:
        raise ValueError("Order not found.")

    data = doc.to_dict() or {}
    stored_email = str(data.get("email", "")).lower()
    if stored_email != email.lower():
        raise PermissionError("Email does not match order.")

    return Order(
        order_id=data["order_id"],
        email=data["email"],
        value=float(data["value"]),
        tracking_id=data["tracking_id"],
    )
