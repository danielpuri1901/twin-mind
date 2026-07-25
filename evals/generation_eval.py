#!/usr/bin/env python3
"""Generation eval - the OTHER half of the RAGAS split (retrieval is generation's sibling).

Retrieval asks "did we fetch the right chunks?" (recall@k, deterministic). Generation asks: given
those chunks, does the LLM WRITE a correct, grounded answer? Two judge metrics, retrieval held
FIXED at the winning config (windowed + contextual, top-10):

  - answer_correctness : does the generated answer match the gold answer? (reference-BASED - we have
                         hand-corrected gold, stronger than RAGAS's reference-free proxy)
  - faithfulness       : is every claim in the answer supported by the retrieved context? (no hallucination)

The split is diagnostic: correct=0 & faithful=1 => the LLM answered faithfully from BAD context (a
retrieval miss); correct=0 & faithful=0 => the LLM HALLUCINATED (a generation fault). One blended
"is the answer good" number can't tell those apart.

Runs on the box (Bedrock instance role). Two Braintrust scorers; one experiment per generator config.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retrieval_eval as RE   # connect, retrieve, embed_query, brt, ROOT, QA

import braintrust

for line in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

PROJECT = "twin-mind"
GEN_MODEL = "eu.anthropic.claude-sonnet-4-6"   # the generator under test (production drafting model)
CTX_DB = os.path.join(RE.ROOT, "index", "vectors-windowed-ctx.db")   # the winning retrieval config
K = 10


# ---------- the generator (the thing being evaluated) ----------

GEN_SYS = ("Answer the question using ONLY the provided context. If the context does not contain the "
           "answer, say you don't know. Be concise - one or two sentences, no preamble.")


def generate(question, chunks):
    ctx = "\n\n".join(f"[{c.get('source','')} {c.get('date','')} {c.get('chat','')}] {c.get('text','')}"
                      for c in chunks)
    r = RE.brt.converse(
        modelId=GEN_MODEL,
        messages=[{"role": "user", "content": [{"text": f"CONTEXT:\n{ctx}\n\nQUESTION: {question}"}]}],
        system=[{"text": GEN_SYS}],
        inferenceConfig={"temperature": 0, "maxTokens": 300})
    return r["output"]["message"]["content"][0]["text"].strip()


# ---------- the two judges (Sonnet, temp 0) ----------

def _judge(system, user, key):
    r = RE.brt.converse(
        modelId=GEN_MODEL,
        messages=[{"role": "user", "content": [{"text": user}]}],
        system=[{"text": system}],
        inferenceConfig={"temperature": 0, "maxTokens": 250})
    txt = r["output"]["message"]["content"][0]["text"]
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    try:
        return bool(json.loads(m.group(0))[key]) if m else False
    except Exception:
        return False


CORRECT_SYS = ('Judge if the CANDIDATE answer is factually correct versus the REFERENCE answer. '
               'Wording may differ; it is correct if the key facts match and nothing contradicts the '
               'reference. Respond strict JSON: {"correct": true|false, "reason": "one sentence"}.')
FAITH_SYS = ('Judge if EVERY factual claim in the ANSWER is supported by the CONTEXT (no outside '
             'knowledge, no invention). "I don\'t know" is faithful. Respond strict JSON: '
             '{"faithful": true|false, "reason": "one sentence"}.')


def judge_correct(question, gold, answer):
    return _judge(CORRECT_SYS, f"QUESTION: {question}\nREFERENCE: {gold}\nCANDIDATE: {answer}", "correct")


def judge_faithful(answer, contexts):
    ctx = "\n\n".join(contexts)
    return _judge(FAITH_SYS, f"CONTEXT:\n{ctx}\n\nANSWER: {answer}", "faithful")


# ---------- Braintrust wiring ----------

def make_task():
    def task(question):
        db = RE.connect(CTX_DB)
        try:
            chunks = RE.retrieve(db, RE.embed_query(question), K)
        finally:
            db.close()
        return {"answer": generate(question, chunks), "contexts": [c.get("text", "") for c in chunks]}
    return task


def answer_correctness(input, output, expected, **kw):
    return 1.0 if judge_correct(input, expected, output["answer"]) else 0.0


def faithfulness(output, **kw):
    return 1.0 if judge_faithful(output["answer"], output["contexts"]) else 0.0


def main():
    rows = [json.loads(l) for l in open(RE.QA, encoding="utf-8")]
    data = [{"input": r["question"], "expected": r["answer"], "metadata": {"id": r["id"]}} for r in rows]
    print(f"corpus-qa: {len(data)} questions | generator={GEN_MODEL} | retrieval=windowed+contextual@{K}")
    braintrust.Eval(
        PROJECT,
        data=data,
        task=make_task(),
        scores=[answer_correctness, faithfulness],
        experiment_name="generation-windowed-contextual",
    )
    print(f"  done -> Braintrust '{PROJECT}' / experiment 'generation-windowed-contextual'")


if __name__ == "__main__":
    main()
