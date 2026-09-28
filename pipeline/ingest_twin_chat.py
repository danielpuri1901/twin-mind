"""Append the twin's own conversations to the corpus, on a timer.

Replaces the session-close hook, which never fired in practice. The first
design cut the day by restarting the gateway at 04:00, on the assumption that
a restart ends the session and fires `on_session_finalize`. It does not: the
session opened 2026-07-20 survived the 2026-09-24 restart and only ended when
Daniel sent /reset on 2026-09-25. So for five nights the restart produced a
Telegram notification and no boundary, while 122 real messages sat in
state.db unindexed.

Memory should not depend on a session ever ending. This reads state.db every
half hour, takes the messages it has not seen, and appends them to the
corpus. A conversation becomes searchable within the hour whether or not the
session closes, and there is nothing to restart.

Idempotent on message id, which is the row id Hermes assigns. The ledger
lives in corpus.db so the write and its bookkeeping share one transaction.

Run with --dry-run to see what it would take without writing.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
STATE_DB = os.environ.get("HERMES_STATE_DB") or os.path.expanduser("~/.hermes/state.db")
FTS_DB = os.path.join(CORPUS, "index", "corpus.db")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")
JSONL = os.path.join(CORPUS, "normalized", "twin-chat.jsonl")
LEGACY_DONE = os.path.join(CORPUS, "normalized", ".twin-chat-ingested")
EMBED_MODEL = "cohere.embed-multilingual-v3"
SOURCE = "twin-chat"
MIN_EMBED_CHARS = 12


def ensure_ledger(fts):
    fts.execute("CREATE TABLE IF NOT EXISTS twin_chat_ingested (message_id INTEGER PRIMARY KEY)")
    fts.commit()


def seed_from_legacy(fts, state):
    """One-time migration: the 2026-09-24 backfill recorded whole sessions, not
    message ids. Mark every message of those sessions as done, or this job
    would insert all 187 records a second time."""
    if fts.execute("SELECT 1 FROM twin_chat_ingested LIMIT 1").fetchone():
        return 0
    try:
        sessions = [ln.strip() for ln in open(LEGACY_DONE) if ln.strip()]
    except FileNotFoundError:
        return 0
    if not sessions:
        return 0
    marks = []
    for sid in sessions:
        marks += [r[0] for r in state.execute(
            "SELECT id FROM messages WHERE session_id=?", (sid,))]
    fts.executemany("INSERT OR IGNORE INTO twin_chat_ingested VALUES (?)",
                    [(m,) for m in marks])
    fts.commit()
    return len(marks)


def pending(state, fts):
    """Messages worth keeping that the ledger has not seen."""
    done = {r[0] for r in fts.execute("SELECT message_id FROM twin_chat_ingested")}
    rows = state.execute(
        "SELECT m.id, m.session_id, m.role, m.content, m.timestamp, s.source "
        "FROM messages m JOIN sessions s ON s.id = m.session_id "
        "WHERE s.source = 'telegram' ORDER BY m.timestamp").fetchall()
    out = []
    for mid, sid, role, content, ts, _src in rows:
        if mid in done:
            continue
        text = (content or "").strip()
        # Tool calls and system turns are not things anyone said.
        if role not in ("user", "assistant") or not text:
            continue
        try:
            date = datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
        except (TypeError, ValueError):
            date = str(ts)[:32]
        out.append({"message_id": mid, "source": SOURCE, "chat": "twin", "date": date,
                    "who": "me" if role == "user" else "twin",
                    "sender": "Daniel" if role == "user" else "Twin Mind",
                    "text": text, "session_id": sid})
    return out


def embed(records):
    """Vector rows for the records worth embedding. Short acks carry nothing to
    match on, so they stay in FTS and out of the index, the same floor
    embed_corpus.load_records uses."""
    import boto3
    import sqlite_vec
    worth = [r for r in records if len(r["text"]) >= MIN_EMBED_CHARS]
    if not worth:
        return 0
    brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
    vecs = []
    for i in range(0, len(worth), 90):  # Cohere v3 takes up to 96 texts per call
        body = json.dumps({"texts": [r["text"][:2048] for r in worth[i:i + 90]],
                           "input_type": "search_document", "truncate": "END"})
        vecs += json.loads(brt.invoke_model(modelId=EMBED_MODEL, body=body)["body"].read())["embeddings"]
    db = sqlite3.connect(VEC_DB, timeout=30)
    try:
        db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
        rid = db.execute("SELECT COALESCE(MAX(rowid),0) FROM vec_meta").fetchone()[0]
        for r, v in zip(worth, vecs):
            rid += 1
            db.execute("INSERT INTO vec_meta VALUES (?,?,?,?,?,?,?)",
                       (rid, r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"]))
            db.execute("INSERT INTO vec_idx(rowid, embedding) VALUES (?,?)",
                       (rid, sqlite_vec.serialize_float32(v)))
        db.commit()
    finally:
        db.close()
    return len(vecs)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    state = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    fts = sqlite3.connect(FTS_DB, timeout=30)
    ensure_ledger(fts)
    seeded = seed_from_legacy(fts, state)
    if seeded:
        print(f"seeded ledger with {seeded} message ids from the 2026-09-24 backfill")

    recs = pending(state, fts)
    print(f"pending records: {len(recs)}")
    if args.dry_run:
        for r in recs[:5]:
            print("   ", r["date"][:16], r["who"], "|", r["text"][:60].replace("\n", " "))
        return 0
    if not recs:
        return 0

    fts.executemany("INSERT INTO msgs VALUES (?,?,?,?,?,?)",
                    [(r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"])
                     for r in recs])
    fts.executemany("INSERT OR IGNORE INTO twin_chat_ingested VALUES (?)",
                    [(r["message_id"],) for r in recs])
    fts.commit()

    os.makedirs(os.path.dirname(JSONL), exist_ok=True)
    with open(JSONL, "a", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps({k: v for k, v in r.items() if k != "message_id"},
                                ensure_ascii=False) + "\n")

    n = embed(recs)
    print(f"appended {len(recs)} records, embedded {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
