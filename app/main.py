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


# ---- Day 8 Guardrails ----
MAX_MESSAGE_CHARS = 2000  # reject huge payloads (basic abuse guard)


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
    - Rate limited per minute per (api_key + ip)
    - Rejects huge messages
    """
    sid = req.session_id or "unknown"

    api_key = caller.get("api_key", "unknown")
    ip = caller.get("ip", request.client.host if request.client else "unknown")

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

    # 2) Rate limit guard
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
        "order_id": req.order_id,
        "email": req.email,
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


@app.get("/health")
def health():
    return {"status": "ok"}
