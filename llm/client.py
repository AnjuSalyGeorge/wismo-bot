import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from llm.schemas import IntentOutput

# Prompt files
INTENT_PROMPT_PATH = Path("prompts/intent_v1.md")
HANDOFF_PROMPT_PATH = Path("prompts/handoff_v1.md")


# ---------------------------
# Generic prompt helpers
# ---------------------------
def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_template(template: str, vars: Dict[str, Any]) -> str:
    """
    Simple template renderer for {var} placeholders.
    (Used for handoff prompt.)
    """
    out = template
    for k, v in vars.items():
        out = out.replace("{" + k + "}", "" if v is None else str(v))
    return out


# ---------------------------
# Intent prompt (strict JSON)
# ---------------------------
def _load_intent_prompt() -> str:
    return load_text(INTENT_PROMPT_PATH)


def _render_intent_prompt(user_message: str) -> str:
    template = _load_intent_prompt()
    # Your intent prompt uses {{user_message}}
    return template.replace("{{user_message}}", user_message)


def _extract_json(text: str) -> Optional[dict]:
    """
    Extract first JSON object from text.
    Handles code fences and models that add extra tokens.
    """
    if not text:
        return None

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    blob = match.group(0).strip()
    try:
        return json.loads(blob)
    except Exception:
        return None


def _normalize_msg(user_message: str) -> str:
    m = (user_message or "").lower()
    m = m.replace("didn’t", "didn't")
    m = re.sub(r"\s+", " ", m).strip()
    return m


def _stub_intent(user_message: str) -> IntentOutput:
    msg = _normalize_msg(user_message)

    # delivered_not_received
    delivered_phrases = ["delivered", "left at door", "front door", "porch"]
    not_received_phrases = [
        "not received",
        "still not received",
        "did not receive", "didn't receive", "didnt receive",
        "did not get", "didn't get", "didnt get",
        "never received",
        "missing",
        "not here",
        "not delivered to me",
    ]

    delivered_like = any(p in msg for p in delivered_phrases)
    not_received_like = any(p in msg for p in not_received_phrases)

    # ✅ covers both: "Delivered but didn't get it" AND "Still not received"
    if (delivered_like and not_received_like) or not_received_like:
        intent = "delivered_not_received"

    # delivery_attempted (includes "tried to deliver", "no one home")
    elif any(
        p in msg
        for p in [
            "attempt",
            "attempted",
            "tried to deliver",
            "delivery attempt",
            "no one was home",
            "nobody was home",
        ]
    ):
        intent = "delivery_attempted"

    # damaged
    elif any(p in msg for p in ["damag", "broken", "cracked", "smash", "torn"]):
        intent = "damaged"

    # return to sender
    elif any(p in msg for p in ["return to sender", "returned", "rts", "sent back"]):
        intent = "return_to_sender"

    # delayed (include "late")
    elif any(p in msg for p in ["delay", "delayed", "late", "taking too long"]):
        intent = "delayed"

    # stuck_in_transit (include "no movement")
    elif any(
        p in msg
        for p in [
            "stuck",
            "not moving",
            "no movement",
            "hasn't moved",
            "hasnt moved",
            "no update",
            "not updated",
        ]
    ):
        intent = "stuck_in_transit"

    else:
        intent = "track_order"

    # Extract order id like A1004
    order_id = None
    m = re.search(r"\bA\d{3,6}\b", user_message or "")
    if m:
        order_id = m.group(0)

    # Extract email
    email = None
    m2 = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", user_message or "")
    if m2:
        email = m2.group(0)

    missing = []
    if not order_id:
        missing.append("order_id")
    if not email:
        missing.append("email")

    return IntentOutput(
        intent=intent,  # type: ignore
        extracted_order_id=order_id,
        extracted_email=email,
        missing_fields=missing,
        risk_flags=[],
        confidence=0.55,
        suggested_next_action="ask_followup" if missing else "proceed",
    )


def _ollama_intent(user_message: str) -> IntentOutput:
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    prompt = _render_intent_prompt(user_message)

    proc = subprocess.run(
        ["ollama", "run", model],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    out = proc.stdout.decode("utf-8", errors="ignore").strip()
    data = _extract_json(out)

    if not data:
        return _stub_intent(user_message)

    try:
        return IntentOutput(**data)
    except Exception:
        return _stub_intent(user_message)


def infer_intent(user_message: str) -> IntentOutput:
    """
    LLM_MODE:
      - local: call Ollama (strict JSON)
      - stub: regex fallback
    """
    mode = os.getenv("LLM_MODE", "stub").lower().strip()
    if mode == "local":
        return _ollama_intent(user_message)
    return _stub_intent(user_message)


# ---------------------------
# Handoff note generation
# ---------------------------
def _stub_handoff(vars: Dict[str, Any]) -> str:
    return (
        f"Order: {vars.get('order_id')} | Email: {vars.get('email')}\n"
        f"Status: {vars.get('status')}\n"
        f"Issue: {vars.get('message')}\n"
        f"Diagnosis: {vars.get('diagnosis')} | Decision: {vars.get('decision')}\n"
        f"Case: {vars.get('case_id')}\n"
        f"Next steps: Review tracking + contact customer + proceed per policy."
    )


def _ollama_generate_text(prompt: str) -> str:
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    proc = subprocess.run(
        ["ollama", "run", model],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    return proc.stdout.decode("utf-8", errors="ignore").strip()


def generate_handoff(vars: Dict[str, Any]) -> str:
    """
    Generates INTERNAL HANDOFF NOTE (<=8 lines) for human agents.
    Uses local LLM if available; otherwise stub.
    """
    mode = os.getenv("LLM_MODE", "stub").lower().strip()

    if not HANDOFF_PROMPT_PATH.exists():
        return _stub_handoff(vars)

    template = load_text(HANDOFF_PROMPT_PATH)
    prompt = render_template(template, vars)

    if mode != "local":
        return _stub_handoff(vars)

    try:
        text = _ollama_generate_text(prompt).strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines[:8]) if lines else _stub_handoff(vars)
    except Exception:
        return _stub_handoff(vars)
