import os
from functools import lru_cache
from google.cloud import firestore


@lru_cache(maxsize=1)
def get_firestore_client():
    """
    Central Firestore client used by the application.
    Auth is provided via GOOGLE_APPLICATION_CREDENTIALS env var.
    """
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if not cred_path:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS is not set. "
            "Run: export GOOGLE_APPLICATION_CREDENTIALS=/workspaces/wismo-bot/.secrets/service-account.json"
        )

    return firestore.Client()
