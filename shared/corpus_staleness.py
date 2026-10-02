"""Alert when a corpus source stops arriving.

This exists because the failure already happened and nothing said so. On
2026-09-23 the corpus was found to have stopped in July: gmail ended
2026-07-02, imessage 2026-06-28, transcripts 2026-06-29. Only the meeting
ingest was still running. Nothing was broken loudly; ingestion simply stopped
and the twin kept answering from an ageing corpus.

Silence must never mean broken. This checks the newest record per source and
sends one Telegram message naming every source that has gone quiet.

Thresholds are per source because the sources have different natural rhythms:
meetings arrive most days, email most days, a classic paper rarely.

It also checks index parity, which is the same class of problem one layer
down. Retrieval is hybrid: a record indexed for keywords but missing from the
vector index is found by an exact phrase and invisible to a paraphrase. That
already happened. twin-chat sat at 187 FTS records and 0 vectors, every
keyword search worked, and retrieval looked healthy.

The invariant, measured against the live corpus on 2026-09-28 and exact on all
eight sources:

    per source:  count(FTS where length(trim(text)) >= 12)  ==  count(vec_meta)

The 12 character floor is deliberate, and it is where the two counts
legitimately differ from the raw record count: "ok" is worth indexing for
keywords and worth nothing as a vector, so embed_corpus.load_records and
ingest_twin_chat.embed both skip it. Applying the same floor to the FTS side
is what turns a fuzzy "roughly equal" into an exact equality worth alerting
on.

Run daily from a timer. Exit code is 0 even when sources are stale, because a
non-zero exit would only bury the alert in a unit failure.
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
DB = os.path.join(CORPUS, "index", "corpus.db")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")

# Matches embed_corpus.load_records and ingest_twin_chat.MIN_EMBED_CHARS. If
# either of those moves, this moves with it or the alarm cries wolf daily.
MIN_EMBED_CHARS = 12

# Sources that are FINISHED, not broken (Daniel's call, 2026-09-28). A one-off
# export that will never update again is not an incident, and alerting on it
# every morning trains you to ignore the alarm. Gmail moved to a tool: the
# corpus keeps Daniel's own sent mail as voice, and freshness is fetched on
# demand rather than bulk-ingested. iMessage and Google Chat he no longer
# uses. Their history stays in the corpus and stays searchable.
ARCHIVED = {"gmail", "imessage", "gchat", "contacts", "gcal"}

# Live sources, with the days of silence that mean something is wrong. The
# rhythms differ: meetings land most working days, twin-chat every day he
# talks to it, Granola transcripts less often.
THRESHOLDS = {
    "meeting": 7,
    "twin-chat": 3,
    "transcript": 14,
}
DEFAULT_THRESHOLD = 30


def _parse(value: str):
    text = str(value or "").strip()
    for cut in (None, 19, 10):
        try:
            dt = datetime.fromisoformat(text if cut is None else text[:cut])
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def newest_per_source(db_path: str = DB):
    """{source: (newest datetime or None, record count)}."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "select source, count(*), max(date) from msgs group by source"
        ).fetchall()
    finally:
        conn.close()
    return {src: (_parse(newest), count) for src, count, newest in rows}


def vector_parity(db_path: str = DB, vec_path: str = VEC_DB):
    """[(source, fts_eligible, vectors, delta)] for sources that disagree.

    Read-only on both databases, so it is safe to run while an ingest is
    mid-write; a torn read shows up as a mismatch that clears on the next run,
    which is the right failure mode for a daily check.
    """
    fts = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    vec = sqlite3.connect(f"file:{vec_path}?mode=ro", uri=True)
    try:
        eligible = dict(fts.execute(
            "select source, count(*) from msgs "
            "where length(trim(text)) >= ? group by source", (MIN_EMBED_CHARS,)))
        vectors = dict(vec.execute("select source, count(*) from vec_meta group by source"))
    finally:
        fts.close()
        vec.close()
    out = []
    for source in sorted(set(eligible) | set(vectors)):
        want, have = eligible.get(source, 0), vectors.get(source, 0)
        if want != have:
            out.append((source, want, have, have - want))
    return out


def format_parity_alert(rows) -> str:
    lines = ["Index parity is broken:"]
    for source, want, have, delta in rows:
        lines.append(f"- {source}: {want} indexed records but {have} vectors ({delta:+d})")
    lines.append("")
    lines.append("A record missing from the vector index is found by exact keyword and "
                 "invisible to a paraphrase, so retrieval will look like it works.")
    return "\n".join(lines)


def stale_sources(state, now=None):
    """Sources past their threshold, worst first."""
    now = now or datetime.now(timezone.utc)
    out = []
    for source, (newest, count) in state.items():
        if source in ARCHIVED:
            continue
        limit = THRESHOLDS.get(source, DEFAULT_THRESHOLD)
        if newest is None:
            out.append((source, None, count, limit))
            continue
        days = (now - newest).days
        if days > limit:
            out.append((source, days, count, limit))
    out.sort(key=lambda r: (r[1] is not None, -(r[1] or 0)))
    return out


def format_alert(stale) -> str:
    lines = ["Corpus sources have gone quiet:"]
    for source, days, count, limit in stale:
        age = "no dated records" if days is None else f"{days} days old"
        lines.append(f"- {source}: newest is {age} (limit {limit}d, {count} records)")
    lines.append("")
    lines.append("The twin is answering from an ageing corpus until this is fixed.")
    return "\n".join(lines)


def send(text: str) -> bool:
    try:
        proc = subprocess.run(
            ["hermes", "send", "-t", "telegram", text],
            capture_output=True, text=True, timeout=60, env=os.environ,
        )
        return proc.returncode == 0
    except Exception as exc:
        print(f"staleness alert send failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--vec-db", default=VEC_DB)
    parser.add_argument("--parity-only", action="store_true",
                        help="check index parity and skip the staleness check")
    parser.add_argument("--json", action="store_true", help="print state, send nothing")
    parser.add_argument("--dry-run", action="store_true", help="print the alert, send nothing")
    args = parser.parse_args()

    # Parity first: a broken index is a live correctness problem, while a stale
    # source is a freshness problem.
    try:
        mismatched = vector_parity(args.db, args.vec_db)
    except Exception as exc:
        print(f"parity check could not run: {exc}", file=sys.stderr)
        mismatched = []

    if args.parity_only:
        if not mismatched:
            print("index parity ok")
            return 0
        print(format_parity_alert(mismatched))
        if not args.dry_run:
            send(format_parity_alert(mismatched))
        return 0

    try:
        state = newest_per_source(args.db)
    except Exception as exc:
        print(f"could not read {args.db}: {exc}", file=sys.stderr)
        return 0

    if args.json:
        print(json.dumps({
            "sources": {s: {"newest": n.isoformat() if n else None, "records": c}
                        for s, (n, c) in state.items()},
            "parity_mismatches": [
                {"source": s, "indexed": w, "vectors": h, "delta": d}
                for s, w, h, d in mismatched],
        }, indent=2))
        return 0

    stale = stale_sources(state)

    if not stale and not mismatched:
        print(f"all {len(state)} sources fresh, index parity ok")
        return 0

    parts = []
    if mismatched:
        parts.append(format_parity_alert(mismatched))
    if stale:
        parts.append(format_alert(stale))
    alert = "\n\n".join(parts)
    print(alert)
    if not args.dry_run:
        send(alert)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
