#!/usr/bin/env python3
"""Align a judge to Daniel's labels as a LangSmith experiment - the standard alignment step.

client.evaluate() runs the judge over its golden dataset. The number is computed in code (fixed
schema, trustworthy) AND it lands as a clickable experiment under
Datasets & Experiments -> <golden dataset> -> Experiments (per-row, in the UI). Run this on every
judge change and read precision/recall vs the labels; the DISAGREEMENTS it prints are the flywheel
fuel - each one is a row to re-label or a judge-prompt fix.

Usage (on the box):
  python3 evals/align.py insight
  python3 evals/align.py coach
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
for _l in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k, _v)

from langsmith import Client

from evals.judges import judge_coach_faithfulness, judge_insight


def _t_insight(inp):
    g = judge_insight(inp["ai_advancements"])
    return {"prediction": int(g.insight_is_real), "reason": g.reason}


def _t_coach(inp):
    g = judge_coach_faithfulness(inp["coach_output"], inp["source"])
    return {"prediction": int(g.coach_faithfulness), "reason": g.reason}


SPECS = {
    "insight": {
        "dataset": "brief-insight-golden",
        "label": "insight_is_real",
        "target": _t_insight,
        "show": lambda inp: " | ".join(str(x) for x in (inp.get("ai_advancements") or []))[:200],
    },
    "coach": {
        "dataset": "coach-faithfulness-golden",
        "label": "coach_faithfulness",
        "target": _t_coach,
        "show": lambda inp: str(inp.get("coach_output"))[:200],
    },
}


def run(name):
    spec = SPECS[name]
    label = spec["label"]

    def agreement(run, example):
        pred = int(bool(run.outputs.get("prediction")))
        ref = int(example.outputs.get(label))
        return {"key": "agreement", "score": 1 if pred == ref else 0}

    client = Client()
    results = client.evaluate(
        spec["target"],
        data=spec["dataset"],
        evaluators=[agreement],
        experiment_prefix=f"align-{name}",
        max_concurrency=4,
    )

    tp = fp = tn = fn = 0
    disagreements = []
    for row in results:
        inp = row["example"].inputs
        pred = int(bool(row["run"].outputs.get("prediction")))
        reason = row["run"].outputs.get("reason", "")
        ref = int(row["example"].outputs.get(label))
        if pred and ref:
            tp += 1
        elif pred and not ref:
            fp += 1
        elif not pred and not ref:
            tn += 1
        else:
            fn += 1
        if pred != ref:
            kind = "fp" if pred else "fn"  # fp = judge YES / you NO; fn = judge NO / you YES
            disagreements.append((kind, pred, ref, spec["show"](inp), reason))

    total = tp + fp + tn + fn
    agree = (tp + tn) / total if total else 0.0
    prec = tp / (tp + fp) if (tp + fp) else float("nan")
    rec = tp / (tp + fn) if (tp + fn) else float("nan")

    print(f"\n=== alignment: {name}  ({spec['dataset']}, n={total}) ===")
    print(f"agreement={agree:.2f}  precision={prec:.2f}  recall={rec:.2f}  "
          f"(tp={tp} fp={fp} tn={tn} fn={fn})")
    print(f"experiment: {getattr(results, 'experiment_name', '?')}")

    print(f"\n=== disagreements ({len(disagreements)}) - judge vs your label ===")
    if not disagreements:
        print("  none - perfect agreement")
    for kind, pred, ref, shown, reason in disagreements:
        gloss = "judge said REAL, you said NOT" if kind == "fp" else "judge said NOT, you said REAL"
        if name == "coach":
            gloss = gloss.replace("REAL", "FAITHFUL").replace("NOT", "UNFAITHFUL")
        print(f"\n  [{kind}] judge={pred} you={ref}  ({gloss})")
        print(f"    input : {shown}")
        print(f"    judge : {reason}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "insight")
