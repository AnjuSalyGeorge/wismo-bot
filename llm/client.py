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
    Handles models that sometimes add extra tokens.
    """
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _stub_intent(user_message: str) -> IntentOutput:
    msg = (user_message or "").lower()

    if "delivered" in msg and ("not" in msg or "didn't" in msg or "did not" in msg or "didnt" in msg):
        intent = "delivered_not_received"
    elif "attempt" in msg or "attempted" in msg:
        intent = "delivery_attempted"
    elif "damag" in msg or "broken" in msg:
        intent = "damaged"
    elif "return to sender" in msg or "returned" in msg or "rts" in msg:
        intent = "return_to_sender"
    elif "delay" in msg:
        intent = "delayed"
    elif "stuck" in msg or "not moving" in msg:
        intent = "stuck_in_transit"
    else:
        intent = "track_order"

    order_id = None
    m = re.search(r"\bA\d{3,6}\b", user_message or "")
    if m:
        order_id = m.group(0)

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
    """
    Safe, deterministic fallback.
    """
    return (
        f"Order: {vars.get('order_id')} | Email: {vars.get('email')}\n"
        f"Status: {vars.get('status')}\n"
        f"Issue: {vars.get('message')}\n"
        f"Diagnosis: {vars.get('diagnosis')} | Decision: {vars.get('decision')}\n"
        f"Case: {vars.get('case_id')}\n"
        f"Next steps: Review tracking + contact customer + proceed per policy."
    )


def _ollama_generate_text(prompt: str) -> str:
    """
    Generate plain text from Ollama.
    Uses subprocess to avoid new dependencies.
    """
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    proc = subprocess.run(
        ["ollama", "run", model],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    out = proc.stdout.decode("utf-8", errors="ignore").strip()
    # For handoff we want plain text, so just return output.
    return out


def generate_handoff(vars: Dict[str, Any]) -> str:
    """
    Generates INTERNAL HANDOFF NOTE (<=8 lines) for human agents.
    Uses local LLM if available; otherwise stub.
    """
    mode = os.getenv("LLM_MODE", "stub").lower().strip()

    # If prompt file doesn't exist yet, fallback safely
    if not HANDOFF_PROMPT_PATH.exists():
        return _stub_handoff(vars)

    template = load_text(HANDOFF_PROMPT_PATH)
    prompt = render_template(template, vars)

    if mode != "local":
        return _stub_handoff(vars)

    try:
        text = _ollama_generate_text(prompt).strip()
        # keep it compact for demo safety
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines[:8]) if lines else _stub_handoff(vars)
    except Exception:
        return _stub_handoff(vars)
