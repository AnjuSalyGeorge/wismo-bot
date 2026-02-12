## WISMO Bot (Where Is My Order) — LangGraph + FastAPI + Firestore
WISMO (Where Is My Order) chatbot using LangGraph, FastAPI, Firestore, and Cloud Run with tool-calling, policies, and human escalation.
### Key Features
- **LangGraph agent flow**: intake → understand → retrieve → decide
- **LLM intent detection** (local Ollama) + **deploy-safe stub mode**
- **Tools**: order lookup, tracking lookup, case creation
- **Policy layer**: deterministic rules for escalation vs self-serve responses
- **Memory**: Firestore session state + active case tracking
- **Guardrails**: API key auth (for /chat), rate limiting, payload limit
- **Evaluation harness**: automated test suite + classification metrics

---


