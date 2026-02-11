import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import defaultdict

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


# ---------------------------
# Metrics helpers
# ---------------------------
def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def compute_classification_metrics(y_true: List[str], y_pred: List[str]) -> Dict[str, Any]:
    labels = sorted(set(y_true) | set(y_pred))

    cm: Dict[str, Dict[str, int]] = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        cm[t][p] += 1

    per_label: Dict[str, Any] = {}
    for lab in labels:
        tp = cm[lab][lab]
        fp = sum(cm[t][lab] for t in labels if t != lab)
        fn = sum(cm[lab][p] for p in labels if p != lab)

        prec = _safe_div(tp, tp + fp)
        rec = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * prec * rec, prec + rec)

        support = sum(cm[lab].values())
        per_label[lab] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": support,
        }

    acc = _safe_div(sum(cm[l][l] for l in labels), len(y_true))
    macro_f1 = _safe_div(sum(per_label[l]["f1"] for l in labels), len(labels))

    return {
        "labels": labels,
        "accuracy": round(acc, 4),
        "macro_f1": round(macro_f1, 4),
        "per_label": per_label,
        "confusion_matrix": cm,
    }


def bool_accuracy(y_true: List[bool], y_pred: List[bool]) -> float:
    return round(_safe_div(sum(t == p for t, p in zip(y_true, y_pred)), len(y_true)), 4)


def _suite_name(row: Dict[str, Any]) -> str:
    s = (row.get("suite") or "core").strip().lower()
    return s if s else "core"


def _evaluate_rows(g, rows: List[Dict[str, Any]], run_id: str) -> Dict[str, Any]:
    total = len(rows)
    passed = 0
    failures: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []

    # metrics trackers
    y_true_intent: List[str] = []
    y_pred_intent: List[str] = []
    y_true_followup: List[bool] = []
    y_pred_followup: List[bool] = []
    y_true_case: List[bool] = []
    y_pred_case: List[bool] = []
    y_true_reuse: List[bool] = []
    y_pred_reuse: List[bool] = []

    for row in rows:
        test_id = row["id"]
        base_session = row.get("session_id", f"eval_{test_id}")
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

        intent: Optional[str] = None
        confidence: Optional[float] = None
        missing_fields: List[str] = []

        for a in reversed(actions or []):
            if "llm_intent" in a and isinstance(a["llm_intent"], dict):
                li = a["llm_intent"]
                intent = li.get("intent")
                missing_fields = li.get("missing_fields") or []
                confidence = li.get("confidence")
                break

        followup_asked = is_followup(reply)
        top = extract_top_action(actions)

        created = top["tool"] == "create_case"
        reused = top["tool"] == "reuse_case"
        case_exists = created or reused
        case_event = "create" if created else ("reuse" if reused else "none")

        expected_intent = row.get("expected_intent")
        expected_followup = row.get("expected_followup")
        expected_case_created = row.get("expected_case_created")
        expected_reuse_case = row.get("expected_reuse_case")  # optional

        ok = True
        reasons: List[str] = []

        if expected_intent is not None and intent != expected_intent:
            ok = False
            reasons.append(f"intent mismatch: expected={expected_intent} got={intent}")

        if expected_followup is not None and followup_asked != expected_followup:
            ok = False
            reasons.append(f"followup mismatch: expected_followup={expected_followup} asked={followup_asked}")

        if expected_case_created is not None and case_exists != bool(expected_case_created):
            ok = False
            reasons.append(
                f"case_created mismatch: expected_case_created={expected_case_created} got_exists={case_exists} tool={top['tool']}"
            )

        # Optional: if test expects reuse specifically
        if expected_reuse_case is not None and reused != bool(expected_reuse_case):
            ok = False
            reasons.append(f"reuse_case mismatch: expected_reuse_case={expected_reuse_case} got_reuse={reused}")

        # --- metrics tracking (only when expected exists) ---
        if expected_intent is not None:
            y_true_intent.append(expected_intent)
            y_pred_intent.append(intent or "unknown")

        if expected_followup is not None:
            y_true_followup.append(bool(expected_followup))
            y_pred_followup.append(bool(followup_asked))

        if expected_case_created is not None:
            y_true_case.append(bool(expected_case_created))
            y_pred_case.append(bool(case_exists))

        if expected_reuse_case is not None:
            y_true_reuse.append(bool(expected_reuse_case))
            y_pred_reuse.append(bool(reused))

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
                    "expected_reuse_case": expected_reuse_case,
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

    metrics: Dict[str, Any] = {}
    if y_true_intent:
        metrics["intent"] = compute_classification_metrics(y_true_intent, y_pred_intent)
    if y_true_followup:
        metrics["followup_accuracy"] = bool_accuracy(y_true_followup, y_pred_followup)
    if y_true_case:
        metrics["case_created_accuracy"] = bool_accuracy(y_true_case, y_pred_case)
    if y_true_reuse:
        metrics["reuse_case_accuracy"] = bool_accuracy(y_true_reuse, y_pred_reuse)

    metrics["task_success_rate"] = round(pass_rate, 4)

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(pass_rate, 4),
        "metrics": metrics,
        "failures": failures[:25],
        "results": results,
    }


def main():
    # Deterministic by default
    os.environ.setdefault("LLM_MODE", "stub")

    g = build_graph()
    prompts = load_jsonl(PROMPTS_PATH)
    run_id = str(int(time.time()))

    suites: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in prompts:
        suites[_suite_name(row)].append(row)

    overall_rows = prompts
    overall = _evaluate_rows(g, overall_rows, run_id)

    print("\n=== WISMO Eval Report (ALL) ===")
    print(f"Total: {overall['total']} | Passed: {overall['passed']} | Failed: {overall['failed']} | Pass rate: {overall['pass_rate']:.2f}%\n")

    if overall["failures"]:
        print("--- Top failures (up to 10) ---\n")
        for f in overall["failures"][:10]:
            print(f"[{f['id']}] session={f['session_id']}")
            for r in f["reasons"]:
                print(f"  - {r}")
            print(f"  got: {f['got']}\n")

    if "intent" in overall["metrics"]:
        m = overall["metrics"]
        print("=== Metrics (ALL) ===")
        print(f"Intent accuracy: {m['intent']['accuracy']}")
        print(f"Intent macro F1: {m['intent']['macro_f1']}")
        if "followup_accuracy" in m:
            print(f"Follow-up accuracy: {m['followup_accuracy']}")
        if "case_created_accuracy" in m:
            print(f"Case-created accuracy: {m['case_created_accuracy']}")
        if "reuse_case_accuracy" in m:
            print(f"Reuse-case accuracy: {m['reuse_case_accuracy']}")
        print("")

    per_suite: Dict[str, Any] = {}
    for sname, rows in suites.items():
        per_suite[sname] = _evaluate_rows(g, rows, run_id)

    # Print per suite
    for sname in sorted(per_suite.keys()):
        s = per_suite[sname]
        print(f"=== Suite: {sname} ===")
        print(f"Total: {s['total']} | Passed: {s['passed']} | Failed: {s['failed']} | Pass rate: {s['pass_rate']:.2f}%")
        if "intent" in s["metrics"]:
            m = s["metrics"]
            print(f"  Intent acc: {m['intent']['accuracy']} | macro F1: {m['intent']['macro_f1']}")
            if "followup_accuracy" in m:
                print(f"  Follow-up acc: {m['followup_accuracy']}")
            if "case_created_accuracy" in m:
                print(f"  Case-created acc: {m['case_created_accuracy']}")
            if "reuse_case_accuracy" in m:
                print(f"  Reuse-case acc: {m['reuse_case_accuracy']}")
        print("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "mode": os.getenv("LLM_MODE", "stub"),
                "overall": overall,
                "suites": per_suite,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
