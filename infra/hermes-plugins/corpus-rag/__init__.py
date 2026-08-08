"""corpus-rag - auto-RAG for the Twin.

The problem (measured): the model decides whether to reach into the corpus, and it decides "no"
115/116 times - or improvises a raw keyword grep instead of calling corpus-search. This removes the
decision. On every non-trivial user turn it runs the corpus-search contract and injects the top hits
as context via Hermes's `pre_llm_call` hook (the one hook whose return value is used - a dict with a
`context` key is prepended to the turn). Retrieval becomes deterministic; the model only judges
relevance, which it is good at.

Design notes:
- We do NOT threshold on the hybrid score: it's negated RRF (rank-based), the same for every query,
  so it carries no absolute relevance. Instead: skip trivially-short/greeting turns, retrieve top-K,
  and frame the injected context so the model ignores it when irrelevant. A calibrated distance gate
  is a v2 (settle it with retrieval_eval).
- FAIL-OPEN: any error, missing corpus, or timeout -> no injection, never break the turn.

Env:
  CORPUS_RAG_K            top hits to inject (default 5)
  CORPUS_SEARCH_PATH      path to corpus_search.py (default ~/super-project/shared/corpus_search.py)
  CORPUS_RAG_MAX_CHARS    per-hit text cap (default 800)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

_K = int(os.environ.get("CORPUS_RAG_K", "5") or "5")
_MAX_CHARS = int(os.environ.get("CORPUS_RAG_MAX_CHARS", "1800") or "1800")  # a whole ~1600-char chunk (truncating mid-chunk can cut the actual answer)
_SEARCH = os.environ.get("CORPUS_SEARCH_PATH") or os.path.expanduser("~/super-project/shared/corpus_search.py")
_MIN_LEN = 12  # below this, a message is a greeting / ack, not a corpus query
_SKIP = {"hi", "hey", "hello", "yo", "sup", "thanks", "thank you", "ok", "okay", "yes", "no",
         "yep", "nope", "cool", "nice", "lol", "next", "stop", "go", "sure"}


def _retrieve(query: str):
    """Call the corpus-search contract as a subprocess; return parsed JSON-line hits, or []."""
    if not os.path.exists(_SEARCH):
        return []
    try:
        proc = subprocess.run(
            [sys.executable, _SEARCH, query, "--k", str(_K)],
            capture_output=True, text=True, timeout=20, env=os.environ,
        )
        return [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    except Exception as exc:  # fail-open
        logger.debug("corpus-rag retrieve failed: %s", exc)
        return []


def _format(hits) -> str:
    blocks = []
    for h in hits[:_K]:
        cite = " · ".join(x for x in [str(h.get("chat", "")), str(h.get("date", ""))[:10]] if x)
        text = (h.get("text") or "").strip()
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + " …"
        blocks.append(f"[{cite}]\n{text}" if cite else text)
    body = "\n\n---\n\n".join(blocks)
    return (
        "RELEVANT CONTEXT auto-retrieved from Daniel's personal corpus (corpus-search). "
        "Ground your answer in this when it is relevant, and cite the source + date. "
        "If it is NOT relevant to the question, ignore it and answer normally. "
        "Report exactly what the source says - do not invent a personal fact, drop an item, or "
        "misattribute a quote. You already have this context, so do NOT run corpus-search or grep again.\n\n"
        + body
    )


def on_pre_llm_call(*, user_message: str = "", conversation_history=None, session_id: str = "",
                    **_: object):
    """Fires once per turn before the tool loop. Return {'context': ...} to inject; None to skip."""
    try:
        msg = (user_message or "").strip()
        if not msg and isinstance(conversation_history, list):  # fall back to the last user turn
            for m in reversed(conversation_history):
                if isinstance(m, dict) and m.get("role") == "user" and (m.get("content") or "").strip():
                    msg = str(m["content"]).strip()
                    break
        if len(msg) < _MIN_LEN or msg.lower().strip("?.! ") in _SKIP:
            return None  # trivial turn - no corpus lookup
        hits = _retrieve(msg)
        if not hits:
            return None
        return {"context": _format(hits)}
    except Exception as exc:  # fail-open - never break a live turn
        logger.debug("corpus-rag pre_llm_call failed: %s", exc)
        return None


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    logger.debug("corpus-rag registered (k=%s, search=%s)", _K, _SEARCH)
