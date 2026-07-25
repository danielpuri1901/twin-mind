#!/usr/bin/env python3
"""Retrieval eval - per-turn vs windowed chunking, context recall@k on corpus-qa.

Isolates the RETRIEVER + CHUNKING (not the generator), per the RAGAS component-eval split
(docs/2026-07-17-corpus-chunking-design.md). Vector lane only: chunking mainly moves semantic
retrieval, and comparing pure KNN top-k is the clean single-variable cut (FTS/BM25 barely cares
about chunk size). Two arms share one corpus snapshot, one embedder, one maxch - the ONLY thing
that differs is how conversational sources are chunked.

Two hit definitions, both reported (deterministic anchor + RAGAS-style judge):
  - entity_recall@k  : fraction of the gold answer's key tokens (proper nouns / numbers / dates)
                       that appear in the concatenated top-k text. Deterministic, reproducible,
                       no LLM. Reported as mean-coverage and as hit-rate (coverage >= 0.5).
  - llm_recall@k     : an LLM judge (Bedrock Sonnet, temp 0) decides whether the top-k retrieved
                       context actually SUPPORTS the gold answer. This is RAGAS `context_recall`.

Run on the box (Bedrock via instance role). Writes results JSONL for the Langfuse/Braintrust mirror.
"""
import argparse
import json
import os
import re
import sqlite3
import sys

import boto3
import sqlite_vec

ROOT = os.environ.get("TWIN_CORPUS", os.path.expanduser("~/twin-corpus"))
QA = os.path.join(ROOT, "datasets", "corpus-qa.jsonl")
OUT = os.path.join(ROOT, "datasets", "retrieval-eval-results.jsonl")
EMBED_MODEL = "cohere.embed-multilingual-v3"
JUDGE_MODEL = "eu.anthropic.claude-sonnet-4-6"
KS = (5, 10, 20)
LLM_K = 10            # judge context-recall at this k (the informative middle)
COVER_HIT = 0.5       # entity coverage >= this counts as a deterministic hit

brt = boto3.client("bedrock-runtime", region_name="eu-west-1")

STOP = {"The", "This", "That", "There", "Daniel", "Also", "When", "What", "Who", "Why", "How",
        "And", "But", "For", "With", "From", "Was", "Were", "Are", "His", "Her", "Him", "She",
        "They", "Yeah", "About", "Into", "Not", "You", "Your"}
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"}


# ---------- retrieval ----------

def embed_query(q):
    body = json.dumps({"texts": [q], "input_type": "search_query", "truncate": "END"})
    r = brt.invoke_model(modelId=EMBED_MODEL, body=body)
    return json.loads(r["body"].read())["embeddings"][0]


def connect(db_path):
    db = sqlite3.connect(db_path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def retrieve(db, qvec, k):
    """Top-k rows by vector distance (KNN), returned in rank order as dicts."""
    knn = db.execute(
        "SELECT rowid, distance FROM vec_idx WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (sqlite_vec.serialize_float32(qvec), k)).fetchall()
    if not knn:
        return []
    ids = [r[0] for r in knn]
    ph = ",".join("?" * len(ids))
    meta = {row[0]: row for row in db.execute(
        f"SELECT rowid, source, chat, date, who, sender, text FROM vec_meta WHERE rowid IN ({ph})", ids)}
    out = []
    for rid, dist in knn:
        m = meta.get(rid)
        if m:
            out.append({"source": m[1], "chat": m[2], "date": m[3], "who": m[4],
                        "sender": m[5], "text": m[6], "distance": dist})
    return out


# ---------- reranking (step 4) ----------

# amazon.rerank-v1 is first-party (no AWS Marketplace subscription needed, unlike cohere.rerank).
RERANK_MODEL = "arn:aws:bedrock:eu-central-1::foundation-model/amazon.rerank-v1:0"
_rr = boto3.client("bedrock-agent-runtime", region_name="eu-central-1")  # Frankfurt = EU-resident


def rerank(query, chunks, top_k=20):
    """Cohere Rerank 3.5 (eu-central-1, in-EU) reorders retrieved chunks by relevance to the query
    and returns the top_k. A home chunk that vector-ranked #11-50 can get pulled into the top."""
    if not chunks:
        return chunks
    docs = [(c.get("text") or "")[:4000] for c in chunks]
    r = _rr.rerank(
        queries=[{"type": "TEXT", "textQuery": {"text": query}}],
        sources=[{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": d}}}
                 for d in docs],
        rerankingConfiguration={"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {
            "numberOfResults": min(top_k, len(docs)),
            "modelConfiguration": {"modelArn": RERANK_MODEL}}})
    return [chunks[res["index"]] for res in r["results"]]


# ---------- deterministic entity recall ----------

def key_tokens(answer):
    """Proper nouns, numbers, years, and month names from the gold answer - the content that
    retrieval must surface. Lowercased for matching."""
    toks = set()
    for w in re.findall(r"[A-Z][a-zA-Z]{2,}", answer):      # proper nouns
        if w not in STOP:
            toks.add(w.lower())
    for n in re.findall(r"\b\d{2,4}\b", answer):            # numbers / years
        toks.add(n)
    for w in re.findall(r"[A-Za-z]+", answer):              # month names
        if w.lower() in MONTHS:
            toks.add(w.lower())
    return toks


def entity_coverage(answer, contexts):
    """Fraction of the answer's key tokens present in the concatenated context text."""
    toks = key_tokens(answer)
    if not toks:
        return None
    blob = " ".join(c["text"] for c in contexts).lower()
    hit = sum(1 for t in toks if t in blob)
    return hit / len(toks)


# ---------- LLM context recall (RAGAS-style) ----------

JUDGE_SYS = (
    "You judge RETRIEVAL quality, not answer quality. Given a QUESTION, the reference ANSWER, and "
    "the CONTEXT passages a retriever returned, decide whether the context contains enough "
    "information to support the reference answer. Judge ONLY what is present in the context - do "
    "not use outside knowledge. Respond with strict JSON: "
    '{\"supported\": true|false, \"reason\": \"one sentence\"}.')


def llm_supported(question, answer, contexts):
    ctx = "\n\n".join(f"[{i+1}] ({c['source']} {c['date']} {c['chat']}) {c['text']}"
                      for i, c in enumerate(contexts))
    user = f"QUESTION:\n{question}\n\nREFERENCE ANSWER:\n{answer}\n\nCONTEXT:\n{ctx}"
    r = brt.converse(
        modelId=JUDGE_MODEL,
        messages=[{"role": "user", "content": [{"text": user}]}],
        system=[{"text": JUDGE_SYS}],
        inferenceConfig={"temperature": 0, "maxTokens": 300})
    txt = r["output"]["message"]["content"][0]["text"]
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    try:
        return bool(json.loads(m.group(0))["supported"]) if m else False
    except Exception:
        return False


# ---------- run one arm ----------

def run_arm(db_path, rows, judge=True):
    db = connect(db_path)
    per_q = []
    for row in rows:
        q, ans = row["question"], row["answer"]
        home = row.get("home")   # {source, chat, date} for rows that carry a known home source
        top = retrieve(db, embed_query(q), max(KS))
        rec = {"id": row["id"], "question": q}
        for k in KS:
            cov = entity_coverage(ans, top[:k])
            rec[f"cover@{k}"] = cov
            rec[f"entity_hit@{k}"] = (cov is not None and cov >= COVER_HIT)
            # deterministic source recall: did top-k include a chunk from the answer's home meeting?
            rec[f"source_hit@{k}"] = (any(c["chat"] == home.get("chat") for c in top[:k]) if home else None)
        rec[f"llm@{LLM_K}"] = llm_supported(q, ans, top[:LLM_K]) if judge else None
        rec["top1"] = {"source": top[0]["source"], "chat": top[0]["chat"], "date": top[0]["date"]} if top else None
        per_q.append(rec)
        c10 = rec["cover@10"]
        print(f"  {row['id']}: cover@10={'n/a' if c10 is None else round(c10, 2)} "
              f"entity_hit@10={rec['entity_hit@10']} llm@10={rec[f'llm@{LLM_K}']}", file=sys.stderr)
    db.close()
    return per_q


def aggregate(per_q):
    n = len(per_q)
    agg = {}
    for k in KS:
        covs = [r[f"cover@{k}"] for r in per_q if r[f"cover@{k}"] is not None]
        agg[f"cover@{k}"] = round(sum(covs) / len(covs), 3) if covs else None
        agg[f"entity_recall@{k}"] = round(sum(1 for r in per_q if r[f"entity_hit@{k}"]) / n, 3)
        sh = [r[f"source_hit@{k}"] for r in per_q if r.get(f"source_hit@{k}") is not None]
        agg[f"source_recall@{k}"] = round(sum(1 for x in sh if x) / len(sh), 3) if sh else None
    llm = [r[f"llm@{LLM_K}"] for r in per_q if r[f"llm@{LLM_K}"] is not None]
    agg[f"llm_recall@{LLM_K}"] = round(sum(1 for x in llm if x) / len(llm), 3) if llm else None
    return agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--perturn", default=os.path.join(ROOT, "index", "vectors-perturn.db"))
    ap.add_argument("--windowed", default=os.path.join(ROOT, "index", "vectors-windowed.db"))
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM context-recall judge")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(QA, encoding="utf-8")]
    print(f"corpus-qa: {len(rows)} questions", file=sys.stderr)

    arms = {}
    for name, path in [("per-turn", a.perturn), ("windowed", a.windowed)]:
        if not os.path.exists(path):
            print(f"MISSING index for {name}: {path}", file=sys.stderr)
            sys.exit(2)
        print(f"\n=== arm: {name} ({path}) ===", file=sys.stderr)
        per_q = run_arm(path, rows, judge=not a.no_judge)
        arms[name] = {"per_q": per_q, "agg": aggregate(per_q)}

    # comparison table
    pt, wd = arms["per-turn"]["agg"], arms["windowed"]["agg"]
    print("\n" + "=" * 62)
    print(f"{'metric':<20}{'per-turn':>12}{'windowed':>12}{'delta':>12}")
    print("-" * 62)
    for m in [f"source_recall@{KS[0]}", f"source_recall@{KS[1]}", f"source_recall@{KS[2]}",
              f"cover@{KS[0]}", f"cover@{KS[1]}", f"cover@{KS[2]}",
              f"entity_recall@{KS[0]}", f"entity_recall@{KS[1]}", f"entity_recall@{KS[2]}",
              f"llm_recall@{LLM_K}"]:
        p, w = pt.get(m), wd.get(m)
        if p is None or w is None:
            continue
        d = w - p
        print(f"{m:<20}{p:>12.3f}{w:>12.3f}{d:>+12.3f}")
    print("=" * 62)

    with open(OUT, "w", encoding="utf-8") as f:
        for name in ("per-turn", "windowed"):
            for r in arms[name]["per_q"]:
                f.write(json.dumps({"arm": name, **r}, ensure_ascii=False) + "\n")
    print(f"\nwrote per-question results -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
