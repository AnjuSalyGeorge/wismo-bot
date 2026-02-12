## Architecture (High-level)

User
  |
  v
FastAPI
  - GET /          -> demo UI (index.html)
  - POST /ui/chat  -> UI chat endpoint (no user API key)
  - POST /chat     -> protected API endpoint (requires X-API-Key)
  |
  v
LangGraph Agent (State Machine)
  1) Intake (session read + store message)
  2) Understand (LLM/stub intent + extract order/email + missing fields)
  3) Retrieve (tools: get_order -> get_tracking)
  4) Decide (diagnosis + policy rules + escalation/case creation)
  |
  v
Tools + Data
  - Firestore sessions (memory)
  - Firestore action logs (observability)
  - Firestore cases (escalations)
  - Orders + Tracking tools (mock / demo)

Switch:
  - LLM_MODE=local -> Ollama (real LLM intent)
  - LLM_MODE=stub  -> deterministic regex intent (deploy-ready)
