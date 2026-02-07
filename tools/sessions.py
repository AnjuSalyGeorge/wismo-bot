# tools/sessions.py
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import get_firestore_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_session(session_id: str) -> Dict[str, Any]:
    db = get_firestore_client()
    ref = db.collection("sessions").document(session_id)
    doc = ref.get()

    if doc.exists:
        data = doc.to_dict() or {}
        # Backfill new fields if missing (non-breaking)
        if "active_case_id" not in data:
            ref.set({"active_case_id": None}, merge=True)
            data["active_case_id"] = None
        if "last_complaint" not in data:
            ref.set({"last_complaint": None}, merge=True)
            data["last_complaint"] = None
        return data

    data = {
        "session_id": session_id,
        "created_at": _now_iso(),
        "last_seen": _now_iso(),
        "order_id": None,
        "email": None,
        "last_intent": None,
        "last_question": None,
        "missing_fields": [],
        "last_complaint": None,
        "active_case_id": None,  # ✅ new
    }
    ref.set(data)
    return data


def update_session(session_id: str, patch: Dict[str, Any]) -> None:
    db = get_firestore_client()
    ref = db.collection("sessions").document(session_id)
    patch = dict(patch)
    patch["last_seen"] = _now_iso()
    ref.set(patch, merge=True)


def append_message(session_id: str, role: str, text: str) -> None:
    db = get_firestore_client()
    ref = (
        db.collection("sessions")
        .document(session_id)
        .collection("messages")
        .document()
    )
    ref.set(
        {
            "ts": _now_iso(),
            "role": role,
            "text": text,
        }
    )


# -----------------------------
# ✅ helpers for case reuse
# -----------------------------
def get_active_case_id(session_id: str) -> Optional[str]:
    sess = get_session(session_id)
    cid = sess.get("active_case_id")
    return cid if isinstance(cid, str) and cid else None


def set_active_case_id(session_id: str, case_id: Optional[str]) -> None:
    update_session(session_id, {"active_case_id": case_id})
