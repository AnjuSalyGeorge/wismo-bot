from fastapi import FastAPI
from app.models import ChatRequest, ChatResponse
from app.graph import build_graph

app = FastAPI(title="WISMO Bot (Day 1)")

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
    }
    out = graph.invoke(state)
    return ChatResponse(
        reply=out["reply"],
        actions_taken=out["actions"],
        case_id=out.get("case_id"),
    )


@app.get("/health")
def health():
    return {"status": "ok"}
