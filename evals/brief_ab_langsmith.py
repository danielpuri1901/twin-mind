#!/usr/bin/env python3
"""Brief composer A/B on LangSmith: UNSTRUCTURED (prompt-and-parse) vs STRUCTURED (forced tool-use).

Same facts, same content instructions - the ONLY variable is the output mechanism. This proves the
project's structured-output rule on a real agent:
  - unstructured: ask for JSON, `re.search`+`json.loads`, and on a parse miss SILENTLY default to an
    empty brief (exactly the anti-pattern in the eight judges).
  - structured:   shared.structured.structured_call - forced tool-use + Pydantic, valid by construction.

Runs two LangSmith experiments (EU, project twin-mind) over the 9 real-morning fixtures. Read them
in the compare view: `schema_valid` = 1.0 for structured by construction vs whatever prompt-parse got.
Grounded in the LangSmith docs: create_dataset -> create_examples -> client.evaluate(target, data,
evaluators, experiment_prefix); evaluators take (inputs, outputs, reference_outputs).
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)                                       # shared
sys.path.insert(0, os.path.join(ROOT, "agents", "brief", "tools"))  # prefetch, compose_brief
for _l in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
    if "=" in _l and not _l.strip().startswith("#"):
        _k, _v = _l.strip().split("=", 1)
        os.environ.setdefault(_k, _v)

from langsmith import Client, traceable
from pydantic import BaseModel
from compose_brief import Brief, SYS, MODEL          # reuse the schema + system prompt
from shared.structured import structured_call, _brt

FIXTURES = os.path.expanduser("~/twin-corpus/datasets/brief-inputs/*.txt")
DATASET = "morning-brief"

JSON_ASK = ("\n\nReturn ONLY a JSON object with keys: needs_you_today (list of {who, what, why_now}), "
            "ai_advancements (list of strings), technical_thing ({concept, code_path, code_quote, "
            "quiz, answer}), coach (string).")


# ---------- the two arms (the ONLY difference is how the output is obtained) ----------

@traceable(run_type="llm", name="unstructured_llm")
def _unstructured_llm(facts):
    r = _brt.converse(modelId=MODEL, system=[{"text": SYS}],
                      messages=[{"role": "user", "content": [{"text": facts + JSON_ASK}]}],
                      inferenceConfig={"temperature": 0, "maxTokens": 3000})
    return r["output"]["message"]["content"][0]["text"]


@traceable(name="brief_unstructured")
def brief_unstructured(inputs):
    txt = _unstructured_llm(inputs["facts"])
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    try:
        brief = Brief.model_validate(json.loads(m.group(0))) if m else None
    except Exception:
        brief = None                       # THE silent default: a parse/shape miss -> empty brief, no error
    return {"valid": brief is not None, "brief": brief.model_dump() if brief else {}, "raw": txt[:400]}


@traceable(name="brief_structured")
def brief_structured(inputs):
    try:
        brief = structured_call(MODEL, SYS, inputs["facts"], Brief, max_tokens=3000)
        return {"valid": True, "brief": brief.model_dump()}
    except Exception as e:
        return {"valid": False, "brief": {}, "error": str(e)[:200]}


# ---------- evaluators (name = metric key; return a bool) ----------

def schema_valid(outputs) -> bool:
    """Did the arm produce a complete, correctly-typed Brief? Structured = True by construction."""
    return bool(outputs.get("valid"))


def sections_complete(outputs) -> bool:
    b = outputs.get("brief") or {}
    t = b.get("technical_thing") or {}
    return bool(b.get("ai_advancements") and b.get("coach")
                and all(t.get(k) for k in ("concept", "code_path", "code_quote", "quiz", "answer")))


class Grade(BaseModel):
    """Whether a morning-brief content set is good: insight (not headlines), grounded, concise, useful."""
    good: bool
    reason: str


@traceable(name="quality_grader")
def quality(outputs) -> bool:
    b = outputs.get("brief")
    if not b:
        return False
    g = structured_call(
        MODEL,
        "You grade the CONTENT quality of a morning brief's sections: are the AI items real insight "
        "(not headlines), is the coach grounded, is it concise and useful? good=true only if you'd be "
        "happy to receive it.",
        json.dumps(b)[:4000], Grade)
    return g.good


def main():
    client = Client()   # reads LANGSMITH_API_KEY + LANGSMITH_ENDPOINT (EU) from env
    examples = [{"inputs": {"facts": open(f, encoding="utf-8").read()}}
                for f in sorted(glob.glob(FIXTURES))]
    print(f"{len(examples)} fixtures -> dataset '{DATASET}'")
    try:
        exists = client.has_dataset(dataset_name=DATASET)
    except Exception:
        exists = False
    if not exists:
        ds = client.create_dataset(dataset_name=DATASET)
        client.create_examples(dataset_id=ds.id, examples=examples)
        print(f"  created dataset with {len(examples)} examples")
    else:
        print("  dataset already exists (reusing)")

    evaluators = [schema_valid, sections_complete, quality]
    for prefix, target in [("without-structured-output", brief_unstructured),
                           ("with-structured-output", brief_structured)]:
        print(f"running experiment {prefix} ...")
        client.evaluate(target, data=DATASET, evaluators=evaluators, experiment_prefix=prefix)
        print(f"  done -> LangSmith experiment '{prefix}'")


if __name__ == "__main__":
    main()
