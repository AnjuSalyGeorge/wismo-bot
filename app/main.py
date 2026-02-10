# app/main.py
import os
from typing import Any

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.models import ChatRequest
from app.graph import build_graph
from app.security import require_api_key
from tools.rate_limit import check_rate_limit
from tools.logs import log_action

app = FastAPI(title="WISMO Bot")

# Templates (Day 10 UI)
templates = Jinja2Templates(directory="app/templates")

graph = build_graph()

# ---- Day 8 Guardrails ----
MAX_MESSAGE_CHARS = 2000  # reject huge payloads (basic abuse guard)


def _extract_llm_fields(actions: list[dict]) -> dict:
    intent = None
    missing_fields = []
    confidence = None
    risk_flags = []

    for a in reversed(actions or []):
        if "llm_intent" in a and isinstance(a["llm_intent"], dict):
            li = a["llm_intent"]
            intent = li.get("intent")
            missing_fields = li.get("missing_fields") or []
            confidence = li.get("confidence")
            risk_flags = li.get("risk_flags") or []
            break

    return {
        "intent": intent,
        "missing_fields": missing_fields,
        "llm_confidence": confidence,
        "risk_flags": risk_flags,
    }


def _run_chat(req: ChatRequest, request: Request, api_key: str) -> dict[str, Any]:
    """
    Shared logic for /chat (protected) and /ui/chat (public UI).
    api_key is used for rate limiting + logging identity.
    """
    sid = req.session_id or "unknown"
    ip = request.client.host if request.client else "unknown"

    # 1) Payload size guard
    msg = req.message or ""
    if len(msg) > MAX_MESSAGE_CHARS:
        log_action(
            sid,
            "blocked_request",
            {
                "reason": "message_too_long",
                "length": len(msg),
                "max": MAX_MESSAGE_CHARS,
                "ip": ip,
                "api_key": api_key,
            },
        )
        raise HTTPException(
            status_code=413,
            detail={"error": "payload_too_large", "message": f"Message too long. Max is {MAX_MESSAGE_CHARS} chars."},
        )

    # 2) Rate limit guard (same policy for both endpoints)
    rl = check_rate_limit(api_key=api_key, ip=ip, limit_per_min=30)
    if not rl["allowed"]:
        log_action(
            sid,
            "blocked_request",
            {
                "reason": "rate_limited",
                "ip": ip,
                "api_key": api_key,
                "count": rl["count"],
                "limit": rl["limit"],
                "bucket": rl["bucket"],
            },
        )
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "message": "Too many requests. Please wait a minute and try again."},
        )

    # Run the graph
    state = {
        "message": req.message,
        "order_id": getattr(req, "order_id", None),
        "email": getattr(req, "email", None),
        "session_id": sid,
        "actions": [],
        "reply": "",
        "case_id": None,
    }

    out = graph.invoke(state)
    actions = out.get("actions", [])
    llm_fields = _extract_llm_fields(actions)

    return {
        "reply": out.get("reply", ""),
        "intent": llm_fields["intent"],
        "missing_fields": llm_fields["missing_fields"],
        "llm_confidence": llm_fields["llm_confidence"],
        "risk_flags": llm_fields["risk_flags"],
        "actions_taken": actions,
        "case_id": out.get("case_id"),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # Simple UI page
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/chat")
def chat(
    req: ChatRequest,
    request: Request,
    caller=Depends(require_api_key),  # ✅ API key auth (from app/security.py)
):
    """
    Protected endpoint:
    - Requires X-API-Key (unless API_KEY env not set -> dev mode allowed)
    - Rate limited per minute per (ip + api_key)
    - Rejects huge messages
    """
    api_key = caller.get("api_key", "unknown")
    return _run_chat(req=req, request=request, api_key=api_key)


@app.post("/ui/chat")
def ui_chat(req: ChatRequest, request: Request):
    """
    Public UI endpoint:
    - No API key required in the browser
    - Uses server-side API_KEY for rate-limit identity/logging
    NOTE: In real deployments you'd lock this down (auth, same-origin, etc.).
    """
    server_key = os.getenv("API_KEY", "").strip()

    # If API_KEY not set, we still allow local demo but isolate rate limits
    api_key = server_key if server_key else "ui-dev"

    return _run_chat(req=req, request=request, api_key=api_key)


@app.get("/health")
def health():
    return {"status": "ok"}
