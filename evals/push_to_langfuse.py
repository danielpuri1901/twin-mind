#!/usr/bin/env python3
"""Mirror local eval datasets into Langfuse for Daniel's visibility (rule 2026-07-15).

Local JSONL under ~/twin-corpus/datasets stays the source of truth (EU-residency,
own-the-crown-jewels). This pushes a copy into Langfuse Datasets so Daniel can see
and use them in the UI. Idempotent: create_dataset is a no-op if it exists, and each
item carries a stable id so re-runs upsert instead of duplicating.

Run on the box (has Langfuse creds + the datasets), or anywhere with the env keys:
  ~/.hermes/hermes-agent/venv/bin/python evals/push_to_langfuse.py
"""
import json, os, sys

# keys are stored HERMES_LANGFUSE_*; the SDK reads LANGFUSE_* - bridge them.
env = {}
for line in open(os.path.expanduser("~/.hermes/.env")):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1); env[k] = v
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", env.get("HERMES_LANGFUSE_PUBLIC_KEY", ""))
os.environ.setdefault("LANGFUSE_SECRET_KEY", env.get("HERMES_LANGFUSE_SECRET_KEY", ""))
os.environ.setdefault("LANGFUSE_HOST", env.get("HERMES_LANGFUSE_BASE_URL", "https://cloud.langfuse.com"))

from langfuse import Langfuse
lf = Langfuse()
if not lf.auth_check():
    print("Langfuse auth failed - check HERMES_LANGFUSE_* keys"); sys.exit(1)

D = os.path.expanduser("~/twin-corpus/datasets")


def load(fn):
    p = os.path.join(D, fn)
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else None


# (file, langfuse dataset name, stable-id fn, input fn, expected fn, metadata fn)
SPECS = [
    ("brief-inbox-decisions.jsonl", "brief-inbox-decisions",
     lambda r: r["id"], lambda r: r["input"], lambda r: r["expected_output"],
     lambda r: {"failure_class": r.get("failure_class"), "assertions": r.get("gold_behavior")}),
    ("brief-section-verdicts.jsonl", "brief-section-verdicts",
     lambda r: f'{r["brief"]}|{r["section"]}', lambda r: {"brief": r["brief"], "section": r["section"]},
     lambda r: r["verdict"], lambda r: {"why": r.get("why"), "labeler": r.get("labeler"), "date": r.get("date")}),
    ("prep-dossier-verdicts.jsonl", "prep-dossier-verdicts",
     lambda r: f'bench-{r.get("bench")}', lambda r: {"meeting": r.get("meeting")},
     lambda r: r.get("verdict"), lambda r: {"notes": r.get("notes"), "labeler": r.get("labeler"), "date": r.get("date")}),
    ("corpus-qa.jsonl", "corpus-qa",
     lambda r: r["id"], lambda r: r["question"], lambda r: r["answer"],
     lambda r: {"citation": r.get("citation"), "corrected": r.get("corrected")}),
    ("brief-archive.jsonl", "brief-archive",
     lambda r: r.get("subject", r.get("date")), lambda r: {"date": r.get("date"), "subject": r.get("subject")},
     lambda r: r.get("body"), lambda r: {}),
]

for fn, name, id_fn, in_fn, exp_fn, meta_fn in SPECS:
    rows = load(fn)
    if not rows:
        print(f"skip {name}: {fn} missing/empty"); continue
    lf.create_dataset(name=name)
    n = 0
    for r in rows:
        # Langfuse item ids are unique per PROJECT across datasets - namespace by dataset.
        lf.create_dataset_item(dataset_name=name, id=f"{name}:{id_fn(r)}",
                               input=in_fn(r), expected_output=exp_fn(r), metadata=meta_fn(r))
        n += 1
    print(f"pushed {name}: {n} items")

lf.flush()
print("done - datasets mirrored to", os.environ["LANGFUSE_HOST"])
