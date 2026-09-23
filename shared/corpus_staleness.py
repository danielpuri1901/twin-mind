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

# Source -> days of silence before it counts as stale.
THRESHOLDS = {
    "meeting": 7,
    "twin-chat": 3,
    "gmail": 7,
    "imessage": 14,
    "transcript": 14,
    "gcal": 14,
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


def stale_sources(state, now=None):
    """Sources past their threshold, worst first."""
    now = now or datetime.now(timezone.utc)
    out = []
    for source, (newest, count) in state.items():
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
    parser.add_argument("--json", action="store_true", help="print state, send nothing")
    parser.add_argument("--dry-run", action="store_true", help="print the alert, send nothing")
    args = parser.parse_args()

    try:
        state = newest_per_source(args.db)
    except Exception as exc:
        print(f"could not read {args.db}: {exc}", file=sys.stderr)
        return 0

    if args.json:
        print(json.dumps(
            {s: {"newest": n.isoformat() if n else None, "records": c}
             for s, (n, c) in state.items()}, indent=2))
        return 0

    stale = stale_sources(state)
    if not stale:
        print(f"all {len(state)} sources fresh")
        return 0

    alert = format_alert(stale)
    print(alert)
    if not args.dry_run:
        send(alert)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
