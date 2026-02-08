import os
from fastapi import Header, HTTPException, Request
from typing import Optional

def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """
    Require X-API-Key header to access protected endpoints.
    Expected key is stored in env var API_KEY.

    Returns caller identity for logging/rate limiting.
    """

    expected = os.getenv("API_KEY", "").strip()

    # If API_KEY is not set → allow dev mode
    if not expected:
        return {
            "api_key": "dev",
            "ip": request.client.host if request.client else "unknown"
        }

    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "unauthorized",
                "message": "Missing or invalid X-API-Key"
            },
        )

    return {
        "api_key": x_api_key.strip(),
        "ip": request.client.host if request.client else "unknown"
    }
