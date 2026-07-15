#!/usr/bin/env python3
"""Arize adapter via the `ax` CLI (the SDK build here lacks datasets/experiments).
Push the 5 datasets, then run the inbox-decision experiment. Comparison note: unlike
Braintrust's one-call Eval(), Arize's flow is manual - run the task yourself, upload
runs referencing example_ids. That friction is itself a finding."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
for l in open(os.path.expanduser("~/.hermes/.env")):
    if "=" in l and not l.strip().startswith("#"):
        k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
import eval_task as E

AX = os.path.expanduser("~/.hermes/hermes-agent/venv/bin/ax")
SPACE = os.environ["ARIZE_SPACE_ID"]
D = os.path.expanduser("~/twin-corpus/datasets")
DATASETS = ["inbox-decision-answers", "brief-verdicts", "prep-verdicts", "qa-answers", "briefs-sent"]


def ax(*args, inp=None):
    r = subprocess.run([AX, *args], capture_output=True, text=True, input=inp, timeout=120)
    return r.returncode, (r.stdout + r.stderr).strip()


def ensure_profile():
    ax("profiles", "create", "default", "--api-key", os.environ["ARIZE_API_KEY"], "--auth-method", "api-key")


def expected_of(r):
    return r.get("expected_output") or r.get("verdict") or r.get("answer") or (r.get("body", "")[:2000])


def flatten(name):
    """Arize wants flat columns; carry a stable example_id."""
    rows = []
    for i, line in enumerate(open(os.path.join(D, name + ".jsonl"))):
        r = json.loads(line)
        eid = str(r.get("id") or r.get("bench") or r.get("subject") or i)
        rows.append({"example_id": eid, "input": json.dumps(r.get("input", r), ensure_ascii=False),
                     "expected_output": str(expected_of(r))})
    return rows


def push_datasets():
    for name in DATASETS:
        p = os.path.join(D, name + ".jsonl")
        if not os.path.exists(p):
            print("skip", name); continue
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for row in flatten(name):
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            tmp = f.name
        rc, out = ax("datasets", "create", "--name", name, "--space", SPACE, "--file", tmp)
        print(f"arize dataset {name}: {'ok' if rc == 0 else 'FAIL'} {out[-120:] if rc else ''}")


def run_experiment():
    runs = []
    for it in E.dataset():
        decision = E.run_task(it["input"])
        runs.append({"example_id": it["id"], "output": decision,
                     "verdict_match": E.score(decision, it["expected_output"])})
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in runs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp = f.name
    rc, out = ax("experiments", "create", "--name", "inbox-decisions",
                 "--dataset", "inbox-decision-answers", "--space", SPACE, "--file", tmp)
    print(f"arize experiment: {'ok' if rc == 0 else 'FAIL'} {out[-200:]}")


if __name__ == "__main__":
    ensure_profile()
    push_datasets()
    run_experiment()
    print("arize done")
