import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from llm.schemas import IntentOutput

PROMPT_PATH = Path("prompts/intent_v1.md")


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _render_prompt(user_message: str) -> str:
    template = _load_prompt()
    return template.replace("{{user_message}}", user_message)


def _extract_json(text: str) -> Optional[dict]:
    """
    Extract first JSON object from text.
    Handles models that sometimes add extra tokens.
    """
    # simple: find first {...} block
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _stub_intent(user_message: str) -> IntentOutput:
    msg = (user_message or "").lower()

    # super simple heuristics (safe fallback)
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

    # extract order_id like A1004
    order_id = None
    m = re.search(r"\bA\d{3,6}\b", user_message or "")
    if m:
        order_id = m.group(0)

    # extract email
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
    prompt = _render_prompt(user_message)

    # Call: ollama run <model>
    # Important: use subprocess so you don't add a new dependency.
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
        # fallback to stub if model output isn't parseable
        return _stub_intent(user_message)

    try:
        return IntentOutput(**data)
    except Exception:
        return _stub_intent(user_message)


def infer_intent(user_message: str) -> IntentOutput:
    """
    LLM_MODE:
      - local: call Ollama
      - stub: regex fallback
    """
    mode = os.getenv("LLM_MODE", "stub").lower().strip()
    if mode == "local":
        return _ollama_intent(user_message)
    return _stub_intent(user_message)
