from fastapi import FastAPI
from app.models import ChatRequest, ChatResponse
from app.graph import build_graph

app = FastAPI(title="WISMO Bot")

graph = build_graph()


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    state = {
        "message": req.message,
        "order_id": req.order_id,
        "email": req.email,
        "session_id": req.session_id,
        "actions": [],
        "reply": "",
        "case_id": None,
        # Day 6 additions (LLM output fields)
        "intent": None,
        "risk_flags": [],
        "missing_fields": [],
        "llm_confidence": None,
    }

    out = graph.invoke(state)

    # Keep response backwards-compatible:
    # reply/actions/case_id are still there.
    # intent/risk_flags/missing_fields/confidence are embedded in actions (or can be added to ChatResponse later).
    return ChatResponse(
        reply=out.get("reply", ""),
        actions_taken=out.get("actions", []),
        case_id=out.get("case_id"),
    )


@app.get("/health")
def health():
    return {"status": "ok"}
