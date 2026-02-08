from datetime import datetime, timezone
from typing import Dict, Any

from app.config import get_firestore_client

try:
    # Firestore atomic increment (best)
    from google.cloud import firestore  # type: ignore
    HAS_FS_INCREMENT = True
except Exception:
    HAS_FS_INCREMENT = False


def _minute_bucket() -> str:
    # stable per-minute bucket like: 202602080523
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M")


def check_rate_limit(api_key: str, ip: str, limit_per_min: int = 30) -> Dict[str, Any]:
    """
    Rate limit: per minute per (api_key + ip)
    Firestore doc: rate_limits/{api_key}:{ip}:{bucket}
    """
    db = get_firestore_client()
    bucket = _minute_bucket()
    doc_id = f"{api_key}:{ip}:{bucket}"
    ref = db.collection("rate_limits").document(doc_id)

    # Read current count
    doc = ref.get()
    data = doc.to_dict() if doc.exists else {}
    current = int(data.get("count", 0))

    # Decide allow/block BEFORE increment? (We increment anyway to track abuse)
    allowed = current < limit_per_min

    # Update count (atomic if possible)
    if HAS_FS_INCREMENT:
        ref.set(
            {"count": firestore.Increment(1), "updated_at": datetime.now(timezone.utc).isoformat()},
            merge=True,
        )
        # After increment, the returned "count" in response is "previous+1" logically
        new_count = current + 1
    else:
        new_count = current + 1
        ref.set(
            {"count": new_count, "updated_at": datetime.now(timezone.utc).isoformat()},
            merge=True,
        )

    return {
        "allowed": allowed,
        "count": new_count,
        "limit": limit_per_min,
        "bucket": bucket,
        "key": doc_id,
    }
