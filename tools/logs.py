from datetime import datetime, timezone
from app.config import get_firestore_client


def log_action(session_id: str, event_type: str, payload: dict) -> None:
    """
    Writes structured logs for every tool call / decision / error.
    Stored in Firestore collection: action_logs
    """
    db = get_firestore_client()
    db.collection("action_logs").add({
        "session_id": session_id or "unknown",
        "event_type": event_type,  # tool_call | decision | error
        "payload": payload,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
