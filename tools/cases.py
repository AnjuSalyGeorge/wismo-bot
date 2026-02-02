import uuid


def create_case(order_id: str, reason: str, user_message: str) -> str:
    return f"CASE-{uuid.uuid4().hex[:8].upper()}"
