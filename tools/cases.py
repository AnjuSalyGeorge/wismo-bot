# tools/cases.py
from datetime import datetime, timezone, timedelta
import uuid
from typing import Optional

from app.config import get_firestore_client


def _now_iso() -> str:
    """Current UTC time in Firestore-friendly ISO format"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    """Safely parse ISO timestamps from Firestore"""
    if not ts:
        return None
    ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def create_case(
    order_id: str,
    reason: str,
    user_message: str,
    email: Optional[str] = None,
    handoff_note: Optional[str] = None,   # ✅ new
    session_id: Optional[str] = None,     # ✅ new (optional)
) -> str:
    """
    Creates a support case in Firestore.
    Email is stored so we can detect repeated claims.
    handoff_note is stored for human agent handoff.
    """
    db = get_firestore_client()

    case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"

    doc = {
        "case_id": case_id,
        "order_id": order_id,
        "reason": reason,
        "status": "open",
        "user_message": user_message,
        "created_at": _now_iso(),
    }

    if email:
        doc["email"] = email
    if session_id:
        doc["session_id"] = session_id
    if handoff_note:
        doc["handoff_note"] = handoff_note

    db.collection("cases").document(case_id).set(doc)
    return case_id


def count_recent_claims_by_email(email: str, days: int = 60) -> int:
    """
    Counts cases for this email in the last N days.

       Implementation avoids Firestore composite indexes
       by querying ONLY on email and filtering by date in Python.
    """
    db = get_firestore_client()

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    q = db.collection("cases").where("email", "==", email)

    count = 0
    for doc in q.stream():
        data = doc.to_dict() or {}
        created_at = data.get("created_at")
        dt = _parse_ts(created_at)
        if dt and dt >= cutoff:
            count += 1

    return count
