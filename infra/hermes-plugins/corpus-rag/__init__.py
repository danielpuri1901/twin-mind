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

Why there is a counter file and not a log line (2026-09-28):
- Whether this plugin fires at all has been an open question since 2026-09-24, and the log was
  never going to settle it. The plugin logs at INFO; the gateway journals WARNING and above, so
  two days of logs contained zero INFO lines. An earlier claim that the logs would answer it was
  wrong.
- So every turn now appends one line to a counter file, outside logging entirely. It records the
  outcome and the reason, never the message text: the corpus is the place for content, and a
  tally that quietly accumulated conversation would be a second uncontrolled copy of it.
- Writing it is best-effort and wrapped, because an instrument that can break the thing it
  measures is worse than no instrument.

Env:
  CORPUS_RAG_K            top hits to inject (default 5)
  CORPUS_SEARCH_PATH      path to corpus_search.py (default ~/super-project/shared/corpus_search.py)
  CORPUS_RAG_MAX_CHARS    per-hit text cap (default 800)
  CORPUS_RAG_STATS        counter file (default ~/twin-corpus/rag-stats.jsonl); empty disables it

Retrieval deliberately does NOT use --time-expand (measured 2026-09-29).

Resolving a relative date into --since/--until looked obviously right, helped
visibly on Daniel's own corpus, and matched a published +6.8% to +11.3%. On 150
LongMemEval questions it made things worse: 0.92 to 0.84 overall, and 0.96 to
0.88 on temporal-reasoning, the bucket it was built for.

The cause is structural. `semantic_rows` applies date filters AFTER the KNN,
over a k*5 overfetch, so a date range does not steer retrieval, it deletes
candidates that retrieval already found. The paper's version indexes each value
by the timestamped events it contains, which is a different mechanism.

The flag still exists on the contract for an explicit "what happened in March"
style query. It is not a default until retrieval can filter inside the KNN.
"""
from __future__ import annotations

import datetime
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
_STATS = os.environ.get(
    "CORPUS_RAG_STATS",
    os.path.join(os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus"),
                 "rag-stats.jsonl"))


def _record(outcome: str, **fields) -> None:
    """Append one line saying what this turn did. No message text, ever.

    One line per turn, so the file grows at the rate Daniel talks rather than
    at the rate the gateway logs, and a day of it is a few kilobytes.
    """
    if not _STATS:
        return
    try:
        row = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "outcome": outcome, **fields}
        os.makedirs(os.path.dirname(_STATS), exist_ok=True)
        with open(_STATS, "a") as fh:
            fh.write(json.dumps(row) + "\n")
    except Exception as exc:  # an instrument must never break what it measures
        logger.debug("corpus-rag stats write failed: %s", exc)


def _norm(text: str) -> set:
    return {w for w in "".join(c if c.isalnum() else " " for c in (text or "").lower()).split()
            if len(w) > 2}


def _is_echo(query: str, text: str, threshold: float = 0.8) -> bool:
    """True when a hit is just the query coming back.

    Daniel's own turns are in the corpus as twin-chat records, so a question he
    has asked before is itself a retrievable record, and it is the closest
    possible match to asking it again. Injecting it tells the model nothing and
    displaces a real hit. Measured 2026-09-28: the top hit was his own earlier
    phrasing on 6 of 8 real questions.

    Containment rather than similarity, because a long stored turn can swallow a
    short question and still be pure echo.
    """
    q, t = _norm(query), _norm(text)
    if not q or not t:
        return False
    return len(q & t) / len(q) >= threshold


def _retrieve(query: str):
    """Call the corpus-search contract as a subprocess; return parsed JSON-line hits, or []."""
    if not os.path.exists(_SEARCH):
        return []
    try:
        # Over-fetch, because dropping echoes must not shrink the injected set.
        proc = subprocess.run(
            [sys.executable, _SEARCH, query, "--k", str(_K + 4)],
            capture_output=True, text=True, timeout=20, env=os.environ,
        )
        hits = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
        kept = [h for h in hits if not _is_echo(query, h.get("text", ""))]
        if len(kept) < len(hits):
            logger.info("corpus-rag dropped %d echo hits", len(hits) - len(kept))
        return kept[:_K]
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
        if not msg:
            _record("skipped", reason="no user message", chars=0)
            return None
        if len(msg) < _MIN_LEN or msg.lower().strip("?.! ") in _SKIP:
            _record("skipped", reason="trivial turn", chars=len(msg))
            return None
        hits = _retrieve(msg)
        if not hits:
            _record("empty", reason="no corpus hits", chars=len(msg))
            return None
        logger.info("corpus-rag injected %d hits (session %s)", len(hits), session_id)
        _record("injected", hits=len(hits), chars=len(msg),
                sources=sorted({str(h.get("source", "")) for h in hits[:_K]}))
        return {"context": _format(hits)}
    except Exception as exc:  # fail-open - never break a live turn
        logger.debug("corpus-rag pre_llm_call failed: %s", exc)
        _record("error", reason=type(exc).__name__)
        return None


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    _record("registered", k=_K, search=_SEARCH)
    logger.debug("corpus-rag registered (k=%s, search=%s)", _K, _SEARCH)
