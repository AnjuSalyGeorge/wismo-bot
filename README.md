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


## 🚀 What This Project Does

The bot helps customers with common delivery issues:

- Delivered but not received  
- Delivery attempted  
- Package damaged  
- Stuck in transit / delayed  
- Returned to sender  
- Simple tracking lookup  

It decides when to:

- Answer automatically  
- Ask follow-up questions  
- Open an investigation  
- Escalate to a human agent  

---

## 🧠 Architecture Overview

**Flow (LangGraph state machine)**  
`intake → understand → retrieve → decide`

### Components

- **FastAPI** – API layer + simple UI  
- **LangGraph Agent** – orchestrates conversation  
- **LLM (Ollama or stub)** – intent extraction only  
- **Tools**  
  - get_order  
  - get_tracking  
  - create_case  
- **Policy Layer** – deterministic business rules  
- **Firestore**  
  - sessions (memory)  
  - action logs (observability)  
  - cases (escalation workflow)  
- **Guardrails**  
  - API key auth  
  - rate limiting  
  - payload limits  

### LLM Strategy

| Mode | Purpose |
|----|----|
| `LLM_MODE=local` | Real intent via Ollama |
| `LLM_MODE=stub` | Deterministic regex (safe + deploy-ready) |

> The LLM is used **only for understanding language**, not for decisions.  
> All business actions are policy-driven and auditable.

---

## 🧪 Evaluation

Automated evaluation harness tests:

- Intent classification  
- Follow-up behavior  
- Case creation / reuse  
- End-to-end conversation logic  

**Metrics**

- Intent accuracy & macro F1  
- Follow-up accuracy  
- Case-created accuracy  
- Reuse-case accuracy  
- Task success rate

Run eval:

```bash
LLM_MODE=stub PYTHONPATH=. python eval/run_eval.py
```

---

## ⚙️ Quickstart

### 1) Install

```bash
pip install -r requirements.txt
```

### 2) Run API

```bash
uvicorn app.main:app --reload
```

Open:

```
http://127.0.0.1:8000
```

---

## 🧩 Example Conversations

**User:**  
> Delivered but not received  

**Bot:**  
> I need a couple details:  
> 1) Order ID  
> 2) Email used for the order  

---

**User:**  
> Order A1004, anju@example.com  

**Bot:**  
> I’m escalating this to a human support agent. I created a case (CASE-X123).  

---

## 🧠 Not RAG — Agent + Tools System

This project is **not a RAG chatbot**.  
It is an **agent-orchestrated system**:

- LLM → intent understanding  
- Tools → real data  
- Policies → decisions  
- Human → escalation  

---

## 🎯 Skills Demonstrated

- LangGraph agent design  
- Tool calling architecture  
- Deterministic policy + LLM hybrid  
- Conversation memory  
- Guardrails & safety  
- Evaluation design  
- Cloud-ready FastAPI service  
- Observability with Firestore  

---

## 🔮 Future Scope

- Real carrier API integration  
- Auth user portal  
- Multilingual intent  
- Agent handoff UI  
- Analytics dashboard  
- Voice channel  

---

## 🎤 How I Explain This in Interviews

> I built a WISMO chatbot using LangGraph and FastAPI.  
> The system uses an LLM only for intent extraction, while all business decisions are handled by deterministic policies and tools.  
> It maintains session memory in Firestore, creates cases for escalation, and includes guardrails like rate limiting.  
> I designed an evaluation harness measuring intent accuracy, macro F1, and case creation behavior.  
> The architecture mirrors real e-commerce support automation.

---

## License

MIT
