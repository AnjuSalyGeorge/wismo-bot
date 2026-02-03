import uuid
from datetime import datetime, timezone
from app.config import get_firestore_client


def create_case(order_id: str, reason: str, user_message: str) -> str:
    db = get_firestore_client()
    case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"

    db.collection("cases").document(case_id).set({
        "case_id": case_id,
        "order_id": order_id,
        "reason": reason,
        "user_message": user_message,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })

    return case_id
