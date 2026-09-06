#!/usr/bin/env python3
"""novelty.py - a reusable "have I surfaced this before?" gate.

The mistake the brief kept making: ask the LLM to remember what it already covered
(a phrase list pasted into the prompt) and "not repeat." It rephrases the same idea and
the injected tail scrolls off, so old items cycle back. Dedup is a DETERMINISTIC fact,
not the model's job.

So instead: keep an append-only store of what the brief ACTUALLY surfaced, each with its
Cohere embedding, and filter new candidates by semantic similarity BEFORE the model sees
them. The model cannot repeat what it never sees. Novelty still needs a real input feed
(you can't dedup your way to new content) - this is the second half of that.

Reused by the brief (AI advancements) and anything else that must not resurface the same
thing daily (e.g. LeadSense). One store file per stream - pass a distinct path per caller.

Embeddings use the same Cohere model + region as the corpus (in-geo, consistent).
Everything fails OPEN: any embedding/store error returns all candidates and never blocks
the caller.
"""
import json
import math
import os
from datetime import datetime

MODEL = "cohere.embed-multilingual-v3"
AI_STORE = "~/.hermes/state/seen-ai.jsonl"   # the brief's AI-advancements stream


def _embed(texts):
    """Cohere embed via Bedrock (batch). Returns a list of vectors, one per input text."""
    import boto3
    brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
    r = brt.invoke_model(modelId=MODEL, body=json.dumps(
        {"texts": [t[:1500] for t in texts], "input_type": "search_document", "truncate": "END"}))
    return json.loads(r["body"].read())["embeddings"]


def _cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _load(store, *, fail_open=True):
    path = os.path.expanduser(store)
    try:
        with open(path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
    except FileNotFoundError:
        return []
    except Exception:
        if fail_open:
            return []
        raise
    if not fail_open and any(not row.get("vec") for row in rows):
        raise ValueError(f"novelty store has unembedded rows: {path}")
    return rows


def filter_novel(candidates, store=AI_STORE, threshold=0.80, fail_open=True):
    """Return the subset of `candidates` (strings) NOT semantically seen before.
    threshold = cosine at/above which a candidate counts as a repeat. Calibrated on real
    Cohere v3 scores (2026-08-15): near-duplicate rephrasings land ~0.90+, a genuinely new
    development on the same topic ~0.61, unrelated items <0.45 - so 0.80 drops rephrasings
    with margin while keeping new developments. Raise to let more through, lower to be
    stricter. Fail-open."""
    candidates = [c for c in candidates if c and c.strip()]
    if not candidates:
        return []
    try:
        seen = [row["vec"] for row in _load(store, fail_open=fail_open) if row.get("vec")]
        if not seen:
            return candidates
        out = []
        for cand, cv in zip(candidates, _embed(candidates)):
            if max((_cos(cv, sv) for sv in seen), default=0.0) < threshold:
                out.append(cand)
        return out
    except Exception:
        return candidates if fail_open else []


def record(items, store=AI_STORE):
    """Append the items the brief actually surfaced (strings) to the store, with embeddings.
    Call this AFTER composing - it records what was shown, so future runs dedup against it."""
    items = [i for i in items if i and i.strip()]
    if not items:
        return
    path = os.path.expanduser(store)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            vecs = _embed(items)
        except Exception:
            vecs = [None] * len(items)   # still log the text; just not dedup-able
        day = datetime.now().strftime("%Y-%m-%d")
        with open(path, "a") as f:
            for text, vec in zip(items, vecs):
                f.write(json.dumps({"date": day, "text": text[:400], "vec": vec}) + "\n")
    except Exception:
        pass
