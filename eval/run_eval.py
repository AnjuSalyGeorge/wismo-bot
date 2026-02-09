import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

# IMPORTANT: allow running from repo root
# Run with: PYTHONPATH=. python eval/run_eval.py
from app.graph import build_graph


PROMPTS_PATH = Path("eval/test_prompts.jsonl")
REPORT_PATH = Path("eval/report.json")


FOLLOWUP_PHRASES = [
    "To help you, I need a couple details",
    "I need a couple details",
    "Please confirm your order ID",
]


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def is_followup(reply: str) -> bool:
    r = (reply or "")
    return any(p in r for p in FOLLOWUP_PHRASES)


def extract_top_action(actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Find decision + whether a case was created/reused.
    """
    decision = None
    tool = None
    case_id = None

    for a in actions or []:
        if "decision" in a:
            decision = a.get("decision")
        if a.get("tool") in {"create_case", "reuse_case"}:
            tool = a.get("tool")
            case_id = a.get("case_id")

    return {"decision": decision, "tool": tool, "case_id": case_id}


def main():
    # Make eval deterministic: use stub unless you explicitly want local
    # If you want Ollama eval, run:
    #   LLM_MODE=local OLLAMA_MODEL=llama3.1:8b PYTHONPATH=. python eval/run_eval.py
    os.environ.setdefault("LLM_MODE", "stub")

    g = build_graph()

    prompts = load_jsonl(PROMPTS_PATH)
    run_id = str(int(time.time()))  # unique per run

    total = len(prompts)
    passed = 0
    failures: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []

    for row in prompts:
        test_id = row["id"]
        base_session = row.get("session_id", f"eval_{test_id}")

        # ✅ Critical: unique session per run so Firestore memory doesn't leak across runs
        session_id = f"{base_session}__run_{run_id}"

        state = {
            "message": row["message"],
            "order_id": row.get("order_id"),
            "email": row.get("email"),
            "session_id": session_id,
            "actions": [],
            "reply": "",
            "case_id": None,
        }

        out = g.invoke(state)

        actions = out.get("actions", [])
        reply = out.get("reply", "")
        intent = None
        confidence = None
        missing_fields = []

        # last llm_intent action
        for a in reversed(actions or []):
            if "llm_intent" in a and isinstance(a["llm_intent"], dict):
                li = a["llm_intent"]
                intent = li.get("intent")
                missing_fields = li.get("missing_fields") or []
                confidence = li.get("confidence")
                break

        followup_asked = is_followup(reply)
        top = extract_top_action(actions)

        # expectations
        expected_intent = row.get("expected_intent")
        expected_followup = row.get("expected_followup")
        expected_case_created = row.get("expected_case_created")

        created = top["tool"] == "create_case"
        reused = top["tool"] == "reuse_case"
        case_event = "create" if created else ("reuse" if reused else "none")

        ok = True
        reasons: List[str] = []

        if expected_intent is not None and intent != expected_intent:
            ok = False
            reasons.append(f"intent mismatch: expected={expected_intent} got={intent}")

        if expected_followup is not None and followup_asked != expected_followup:
            ok = False
            reasons.append(f"followup mismatch: expected_followup={expected_followup} asked={followup_asked}")

        if expected_case_created is not None:
            # interpret expected_case_created as "a case exists for this interaction"
            # ✅ both create_case and reuse_case count as "case exists"
            case_exists = created or reused
            if case_exists != expected_case_created:
                ok = False
                reasons.append(
                    f"case_created mismatch: expected_case_created={expected_case_created} got_exists={case_exists} tool={top['tool']}"
                )

        if ok:
            passed += 1
        else:
            failures.append(
                {
                    "id": test_id,
                    "session_id": session_id,
                    "reasons": reasons,
                    "got": {
                        "reply": reply,
                        "intent": intent,
                        "missing_fields": missing_fields,
                        "confidence": confidence,
                        "decision": top["decision"],
                        "tool": top["tool"],
                        "case_id": top["case_id"],
                        "case_event": case_event,
                    },
                }
            )

        results.append(
            {
                "id": test_id,
                "session_id": session_id,
                "message": row["message"],
                "expected": {
                    "expected_intent": expected_intent,
                    "expected_followup": expected_followup,
                    "expected_case_created": expected_case_created,
                },
                "got": {
                    "reply": reply,
                    "intent": intent,
                    "missing_fields": missing_fields,
                    "confidence": confidence,
                    "decision": top["decision"],
                    "tool": top["tool"],
                    "case_id": top["case_id"],
                    "case_event": case_event,
                },
                "pass": ok,
            }
        )

    pass_rate = (passed / total) * 100 if total else 0.0

    print("\n=== WISMO Eval Report ===")
    print(f"Total: {total} | Passed: {passed} | Failed: {total - passed} | Pass rate: {pass_rate:.2f}%\n")

    if failures:
        print("--- Top failures (up to 10) ---\n")
        for f in failures[:10]:
            print(f"[{f['id']}] session={f['session_id']}")
            for r in f["reasons"]:
                print(f"  - {r}")
            print(f"  got: {f['got']}\n")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": pass_rate,
                "failures": failures[:25],
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
