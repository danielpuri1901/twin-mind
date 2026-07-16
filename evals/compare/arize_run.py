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
DATASETS = ["brief-inbox-decisions", "brief-section-verdicts", "prep-dossier-verdicts", "corpus-qa", "brief-archive"]


def ax(*args, inp=None):
    r = subprocess.run([AX, *args], capture_output=True, text=True, input=inp, timeout=120)
    return r.returncode, (r.stdout + r.stderr).strip()


def ensure_profile():
    # EU account -> region eu-west-1a (US default 401s an EU key). create-or-update.
    region = os.environ.get("ARIZE_REGION", "eu-west-1a")
    ax("profiles", "create", "default", "--api-key", os.environ["ARIZE_API_KEY"],
       "--auth-method", "api-key", "--region", region)
    ax("profiles", "update", "default", "--api-key", os.environ["ARIZE_API_KEY"], "--region", region)


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
                 "--dataset", "brief-inbox-decisions", "--space", SPACE, "--file", tmp)
    print(f"arize experiment: {'ok' if rc == 0 else 'FAIL'} {out[-200:]}")


def run_brief_experiment(limit=24):
    rows = E.brief_sections(limit)
    # 1. create the brief-sections dataset (flattened, stable example_id)
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in rows:
            f.write(json.dumps({"example_id": r["id"],
                                "input": json.dumps({"section": r["section"], "brief_text": r["brief_text"]}),
                                "expected_output": r["label"]}, ensure_ascii=False) + "\n")
        dtmp = f.name
    ax("datasets", "create", "--name", "brief-sections", "--space", SPACE, "--file", dtmp)
    # 2. run the LLM judge locally, upload runs with the agreement score
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for r in rows:
            verdict, reasoning = E.judge_section(r["brief_text"], r["section"])
            f.write(json.dumps({"example_id": r["id"], "output": verdict,
                                "judge_agrees_daniel": E.judge_agrees(verdict, r["label"]),
                                "reasoning": reasoning}, ensure_ascii=False) + "\n")
        rtmp = f.name
    rc, out = ax("experiments", "create", "--name", "brief-judge",
                 "--dataset", "brief-sections", "--space", SPACE, "--file", rtmp)
    print(f"arize brief-judge experiment: {'ok' if rc == 0 else 'FAIL'} {out[-160:]}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--limit", type=int, default=24)
    a = ap.parse_args()
    ensure_profile()
    if a.brief:
        run_brief_experiment(a.limit)
    else:
        push_datasets()
        run_experiment()
    print("arize done")
