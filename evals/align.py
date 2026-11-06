#!/usr/bin/env python3
"""Align a judge to Daniel's labels as a Langfuse experiment - the standard alignment step.

run_experiment() runs the judge over its golden dataset. The number is computed in code (fixed
schema, trustworthy) AND it lands as a clickable experiment run under
Datasets -> <golden dataset> -> Runs (per-row, in the UI). Run this on every judge change and read
precision/recall vs the labels; the DISAGREEMENTS it prints are the flywheel fuel - each one is a
row to re-label or a judge-prompt fix. The golden datasets moved from LangSmith on 2026-10-28.

Usage (on the box):
  python3 evals/align.py insight
  python3 evals/align.py coach
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
for _l in open(os.path.expanduser("~/.twin-mind/.env"), encoding="utf-8"):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k, _v)

from langfuse import Evaluation

from evals.judges import judge_coach_faithfulness, judge_insight
from shared.structured import get_client


def _t_insight(inp):
    g = judge_insight(inp["ai_advancements"])
    return {"prediction": int(g.insight_is_real), "reason": g.reason}


def _t_coach(inp):
    g = judge_coach_faithfulness(inp["coach_output"], inp["source"])
    return {"prediction": int(g.coach_faithfulness), "reason": g.reason}


# floor_* are the CI gate thresholds: a judge change that drops below these fails the ship gate,
# exactly like a failing unit test. Set from the measured baseline with headroom (insight: 0.94/1.00).
SPECS = {
    "insight": {
        "dataset": "brief-insight-golden",
        "label": "insight_is_real",
        "target": _t_insight,
        "show": lambda inp: " | ".join(str(x) for x in (inp.get("ai_advancements") or []))[:200],
        "floor_agreement": 0.85,
        "floor_precision": 0.90,
    },
    "coach": {
        "dataset": "coach-faithfulness-golden",
        "label": "coach_faithfulness",
        "target": _t_coach,
        "show": lambda inp: str(inp.get("coach_output"))[:200],
        "floor_agreement": 0.80,
        "floor_precision": 0.85,
    },
}


def run(name):
    if get_client is None:
        sys.exit("align.py needs Langfuse keys: LANGFUSE_* or HERMES_LANGFUSE_* (the box has them in ~/.twin-mind/.env)")
    spec = SPECS[name]
    label = spec["label"]

    def task(*, item, **_):
        return spec["target"](item.input)

    def agreement(*, output, expected_output, **_):
        pred = int(bool(output.get("prediction")))
        return Evaluation(name="agreement", value=1 if pred == int(expected_output.get(label)) else 0)

    results = get_client().get_dataset(spec["dataset"]).run_experiment(
        name=f"align-{name}",
        task=task,
        evaluators=[agreement],
        max_concurrency=4,
    )

    tp = fp = tn = fn = 0
    disagreements = []
    for row in results.item_results:
        if row.output is None:
            raise RuntimeError(f"judge failed on dataset item {row.item.id}; alignment would be wrong")
        inp = row.item.input
        pred = int(bool(row.output.get("prediction")))
        reason = row.output.get("reason", "")
        ref = int(row.item.expected_output.get(label))
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
    print(f"experiment run: {results.run_name}")
    get_client().flush()

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

    return {"agreement": agree, "precision": prec, "recall": rec,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "n": total}


def gate(name):
    """CI gate: run alignment, exit non-zero if the judge falls below its floor (a judge
    regression blocks the ship, like a failing test)."""
    import math
    spec = SPECS[name]
    fa, fp = spec["floor_agreement"], spec["floor_precision"]
    m = run(name)
    agree_ok = m["agreement"] >= fa
    prec_ok = (not math.isnan(m["precision"])) and m["precision"] >= fp
    if agree_ok and prec_ok:
        print(f"\nJUDGE GATE [{name}]: PASS  "
              f"(agreement {m['agreement']:.2f} >= {fa}, precision {m['precision']:.2f} >= {fp})")
        return 0
    print(f"\nJUDGE GATE [{name}]: FAIL  "
          f"(agreement {m['agreement']:.2f} vs floor {fa}, precision {m['precision']:.2f} vs floor {fp})")
    return 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    is_gate = "--gate" in argv
    names = [a for a in argv if not a.startswith("--")] or ["insight"]
    if is_gate:
        sys.exit(gate(names[0]))
    run(names[0])
