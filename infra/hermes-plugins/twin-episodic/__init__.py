"""twin-episodic - the twin remembers days, not one endless context window.

The problem (measured 2026-09-23): the twin's long-term memory WAS its context
window. One Telegram session had been open since 2026-07-20 with 2,259 of its
messages compacted away. Anthropic's own guidance is explicit that compaction
works inside a session and that memory is the only cross-session mechanism;
LangChain calls the same split thread-scoped versus namespaced. Twin Mind had
the semantic tier (corpus) and the procedural tier (SOUL, skills) but no
episodic tier at all.

This plugin is that tier:

- `on_session_finalize` / `on_session_reset`: the finished conversation is
  written into the corpus as the `twin-chat` source, in the same record shape
  as every other source, so `corpus-search` covers it with no new contract.
- `on_pre_llm_call`: on the FIRST turn of a new session only, yesterday's last
  exchanges and open threads are injected. Mechanical, no model call, hard
  character cap. A generated digest would be a summary that becomes the
  memory, which is the failure mode this replaces.

Every later turn returns None so corpus-rag keeps the turn to itself.

FAIL-OPEN everywhere: a memory bug must never break a live conversation or
lose a session.

Env:
  TWIN_CORPUS_DIR        corpus root (default ~/twin-corpus)
  TWIN_EPISODIC_TURNS    exchanges injected at day start (default 12)
  TWIN_EPISODIC_MAX_CHARS cap on the injected block (default 4000)
  TWIN_EPISODIC_MAX_AGE_HOURS how stale the last conversation may be (default 36)
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys
from collections import deque
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
_JSONL = os.path.join(_CORPUS, "normalized", "twin-chat.jsonl")
_DB = os.path.join(_CORPUS, "index", "corpus.db")
_DONE = os.path.join(_CORPUS, "normalized", ".twin-chat-ingested")
_TURNS = int(os.environ.get("TWIN_EPISODIC_TURNS", "12") or "12")
_MAX_CHARS = int(os.environ.get("TWIN_EPISODIC_MAX_CHARS", "4000") or "4000")
_MAX_AGE_HOURS = int(os.environ.get("TWIN_EPISODIC_MAX_AGE_HOURS", "36") or "36")
_SOURCE = "twin-chat"

# One session is injected per process start, so a long day is not re-primed on
# every turn. The gateway is one process per session in practice; the guard is
# belt and braces.
_primed: set = set()


def _export(session_id: str):
    """The finished session as message dicts, via the supported CLI contract."""
    try:
        proc = subprocess.run(
            ["hermes", "sessions", "export", "--session-id", session_id, "-"],
            capture_output=True, text=True, timeout=60, env=os.environ,
        )
        return [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    except Exception as exc:  # fail-open
        logger.warning("twin-episodic export failed for %s: %s", session_id, exc)
        return []


def _records(messages, session_id: str):
    """Message dicts to corpus records. Same shape as every other source."""
    out = []
    for m in messages:
        role = str(m.get("role") or "")
        text = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue  # tool calls and system turns are not things anyone said
        ts = m.get("timestamp") or m.get("created_at") or ""
        try:
            date = datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
        except (TypeError, ValueError):
            date = str(ts)[:32]
        out.append({
            "source": _SOURCE,
            "chat": "twin",
            "date": date,
            "who": "me" if role == "user" else "twin",
            "sender": "Daniel" if role == "user" else "Twin Mind",
            "text": text,
            "session_id": session_id,
        })
    return out


def _already_done(session_id: str) -> bool:
    try:
        with open(_DONE) as fh:
            return session_id in {ln.strip() for ln in fh}
    except FileNotFoundError:
        return False
    except Exception:
        return False


def _mark_done(session_id: str) -> None:
    try:
        os.makedirs(os.path.dirname(_DONE), exist_ok=True)
        with open(_DONE, "a") as fh:
            fh.write(session_id + "\n")
    except Exception as exc:
        logger.warning("twin-episodic could not mark %s done: %s", session_id, exc)


def _write(records) -> int:
    """Append to the normalized file and upsert into the search index."""
    if not records:
        return 0
    os.makedirs(os.path.dirname(_JSONL), exist_ok=True)
    with open(_JSONL, "a") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    try:
        conn = sqlite3.connect(_DB, timeout=30)
        cols = {r[1] for r in conn.execute("pragma table_info(msgs)")}
        keys = [k for k in ("source", "chat", "date", "who", "sender", "text") if k in cols]
        conn.executemany(
            f"insert into msgs ({','.join(keys)}) values ({','.join('?' * len(keys))})",
            [tuple(r[k] for k in keys) for r in records],
        )
        conn.commit()
        conn.close()
    except Exception as exc:  # the jsonl is the durable copy; the index can be rebuilt
        logger.warning("twin-episodic index write failed: %s", exc)
    return len(records)


def _ingest(session_id: str, reason: str = "") -> int:
    if not session_id or _already_done(session_id):
        return 0
    records = _records(_export(session_id), session_id)
    n = _write(records)
    _mark_done(session_id)
    logger.info("twin-episodic wrote %d records from %s (%s)", n, session_id, reason)
    return n


def _parse_date(value: str):
    """Parse a corpus date, or None. Formats vary by source, so never compare
    these as strings: the corpus holds both "2026-06-28" and
    "2017-01-04T22:23:00+01:00"."""
    text = str(value or "").strip()
    for cut in (None, 19, 10):
        try:
            dt = datetime.fromisoformat(text if cut is None else text[:cut])
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _yesterday_block() -> str:
    """The tail of the last conversation, verbatim. No model call.

    Recency is judged from the newest record, not a rolling window: after a
    daily cut the thing to carry forward is the previous session, whenever it
    happened to end.
    """
    try:
        with open(_JSONL) as fh:
            rows = []
            for ln in deque(fh, maxlen=_TURNS * 8):
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    continue
        if not rows:
            return ""
        newest = _parse_date(rows[-1].get("date"))
        if newest is None:
            return ""
        age = datetime.now(timezone.utc) - newest
        if age > timedelta(hours=_MAX_AGE_HOURS):
            return ""  # nothing recent enough to be "where we left off"
        recent = rows[-(_TURNS * 2):]
        lines = [f"{r.get('sender', '?')}: {r.get('text', '')}" for r in recent]
        # An open thread is mechanical on purpose: something Daniel asked that
        # the day may have closed over. No model decides what mattered.
        open_threads = [
            r["text"] for r in rows
            if r.get("who") == "me" and str(r.get("text", "")).rstrip().endswith("?")
        ][-5:]
        block = "WHERE WE LEFT OFF (verbatim, from the last conversation):\n" + "\n".join(lines)
        if open_threads:
            block += "\n\nOPEN THREADS Daniel raised:\n" + "\n".join("- " + t for t in open_threads)
        block += (
            "\n\nThis is the recent transcript, not a summary. For anything older, "
            "search the corpus; do not guess."
        )
        if len(block) > _MAX_CHARS:
            block = block[-_MAX_CHARS:]
        return block
    except FileNotFoundError:
        return ""
    except Exception as exc:
        logger.debug("twin-episodic day-start block failed: %s", exc)
        return ""


def on_session_finalize(*, session_id: str = "", reason: str = "", **_: object):
    """Fires on shutdown, /new and /reset. The day is over; write it down."""
    try:
        _ingest(session_id, reason or "finalize")
    except Exception as exc:  # never block a shutdown
        logger.warning("twin-episodic finalize failed: %s", exc)
    return None


def on_session_reset(*, session_id: str = "", reason: str = "", **_: object):
    try:
        _ingest(session_id, reason or "reset")
    except Exception as exc:
        logger.warning("twin-episodic reset failed: %s", exc)
    return None


def on_pre_llm_call(*, session_id: str = "", conversation_history=None, **_: object):
    """Inject the day-start block on the first turn of a session only."""
    try:
        if session_id in _primed:
            return None
        history = conversation_history if isinstance(conversation_history, list) else []
        turns = sum(1 for m in history if isinstance(m, dict) and m.get("role") == "user")
        if turns > 1:
            _primed.add(session_id)
            return None
        _primed.add(session_id)
        block = _yesterday_block()
        return {"context": block} if block else None
    except Exception as exc:  # fail-open
        logger.debug("twin-episodic pre_llm_call failed: %s", exc)
        return None


def register(ctx) -> None:
    logger.info("twin-episodic registered (corpus=%s)", _CORPUS)
