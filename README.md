## WISMO Bot (Where Is My Order) - LangGraph + FastAPI + Firestore
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

## Overview

WISMO Bot is a production‑oriented customer support assistant that:

-   Understands user intent from natural language
-   Retrieves order and tracking information via tools
-   Applies business policies to decide next actions
-   Escalates to human agents when required
-   Maintains session memory in Firestore
-   Exposes both API and simple UI

The design separates **language understanding** from **business logic**,
ensuring predictable behavior suitable for real support environments.

------------------------------------------------------------------------

## Architecture

### Components

1.  **FastAPI Service**
    -   `/chat` -- authenticated API endpoint
    -   `/ui/chat` -- browser demo endpoint
    -   `/health` -- readiness check
2.  **LangGraph Agent**
    -   State machine orchestration
    -   Intent extraction via LLM or stub mode
    -   Tool calling for data retrieval
    -   Policy evaluation before response
3.  **Tools Layer**
    -   Order lookup
    -   Tracking lookup
    -   Case creation / reuse
    -   Action logging
4.  **Data & Memory (Firestore)**
    -   Session state
    -   Action audit logs
    -   Escalation cases
5.  **Evaluation Harness**
    -   Automated JSONL test suite
    -   Intent & policy metrics
    -   Regression protection

### Flow

Intake → Understand → Retrieve → Decide → Respond → Escalate (if
required)

------------------------------------------------------------------------

## Modes

| Mode           | Purpose |
|----------------|---------|
| `LLM_MODE=local` | Use Ollama for real intent understanding |
| `LLM_MODE=stub`  | Deterministic regex-based intent routing for deployment |

------------------------------------------------------------------------

## Installation

``` bash
pip install -r requirements.txt
```

## Run Locally

``` bash
LLM_MODE=local OLLAMA_MODEL=llama3.1:8b uvicorn app.main:app --reload
```

Open: http://127.0.0.1:8000

------------------------------------------------------------------------

## Evaluation

Run full test suite:

``` bash
PYTHONPATH=. python eval/run_eval.py
```

Outputs:

-   Intent accuracy & macro F1
-   Follow‑up accuracy
-   Case creation accuracy
-   Detailed failure report

------------------------------------------------------------------------

## API Usage

### Request

POST /chat

``` json
{
  "session_id": "demo1",
  "message": "Delivered but not received"
}
```

### Response

``` json
{
  "reply": "...",
  "intent": "delivered_not_received",
  "missing_fields": ["order_id","email"],
  "case_id": null
}
```

------------------------------------------------------------------------

## Security & Guardrails

-   API key authentication
-   Rate limiting per IP/key
-   Max payload size
-   Deterministic policy layer
-   Audit logging

------------------------------------------------------------------------

## Repository Structure

-   app/ -- FastAPI & LangGraph
-   tools/ -- integrations
-   policies/ -- business rules
-   eval/ -- test harness
-   docs/ -- diagrams

------------------------------------------------------------------------

## Future Enhancements

-   Real carrier integration
-   Authentication portal
-   Analytics dashboard
-   SLA timers
-   Voice interface

------------------------------------------------------------------------

## License

MIT

