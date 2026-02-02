from app.models import Order

MOCK_ORDERS = {
    "A1001": Order(order_id="A1001", email="anju@example.com", value=120.0, tracking_id="T9001"),
    "A2002": Order(order_id="A2002", email="anju@example.com", value=420.0, tracking_id="T9002"),  # high value
}


def get_order(order_id: str, email: str) -> Order:
    order = MOCK_ORDERS.get(order_id)
    if not order:
        raise ValueError("Order not found.")
    if order.email.lower() != email.lower():
        raise PermissionError("Email does not match order.")
    return order
