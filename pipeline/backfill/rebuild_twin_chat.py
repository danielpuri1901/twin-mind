"""Rebuild twin-chat from state.db, which is the authoritative record.

Why a rebuild rather than a patch. The 2026-09-24 backfill read sessions
through `hermes sessions export`, which returns a session's ACTIVE messages
and not its compacted ones. The July session held 2,259 compacted messages
against 56 active, so the backfill captured the tail and missed the body:
187 records where 1,918 turns existed. The 2026-09-28 ledger seed then marked
every message id in those sessions as done, so the timer would never have
gone back for them.

state.db keeps every message, compacted or not. Dropping the 269 partial
records and re-deriving from state.db is simpler than reconciling by text,
and it cannot double-write, because the ledger is rebuilt from the same pass.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
STATE_DB = os.path.expanduser("~/.hermes/state.db")
FTS_DB = os.path.join(CORPUS, "index", "corpus.db")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")
JSONL = os.path.join(CORPUS, "normalized", "twin-chat.jsonl")
EMBED_MODEL = "cohere.embed-multilingual-v3"
# Must equal shared/embedding.MAX_CHARS. Pinned by evals/test_embedding_contract.py,
# which fails if any writer drifts.
MAX_EMBED_CHARS = 2048
SOURCE = "twin-chat"
MIN_EMBED_CHARS = 12


def collect(state):
    rows = state.execute(
        "SELECT m.id, m.role, m.content, m.timestamp FROM messages m "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE s.source='telegram' AND m.role IN ('user','assistant') "
        "AND trim(coalesce(m.content,'')) != '' ORDER BY m.timestamp, m.id").fetchall()
    out = []
    for mid, role, content, ts in rows:
        try:
            date = datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
        except (TypeError, ValueError):
            date = str(ts)[:32]
        out.append({"message_id": mid, "source": SOURCE, "chat": "twin", "date": date,
                    "who": "me" if role == "user" else "twin",
                    "sender": "Daniel" if role == "user" else "Twin Mind",
                    "text": (content or "").strip()})
    return out


def wipe(fts):
    n = fts.execute("SELECT count(*) FROM msgs WHERE source=?", (SOURCE,)).fetchone()[0]
    fts.execute("DELETE FROM msgs WHERE source=?", (SOURCE,))
    fts.execute("CREATE TABLE IF NOT EXISTS twin_chat_ingested (message_id INTEGER PRIMARY KEY)")
    fts.execute("DELETE FROM twin_chat_ingested")
    fts.commit()
    import sqlite_vec
    v = sqlite3.connect(VEC_DB, timeout=30)
    v.enable_load_extension(True); sqlite_vec.load(v); v.enable_load_extension(False)
    ids = [r[0] for r in v.execute("SELECT rowid FROM vec_meta WHERE source=?", (SOURCE,))]
    for rid in ids:
        v.execute("DELETE FROM vec_idx WHERE rowid=?", (rid,))
        v.execute("DELETE FROM vec_meta WHERE rowid=?", (rid,))
    v.commit(); v.close()
    if os.path.exists(JSONL):
        os.replace(JSONL, JSONL + ".pre-rebuild")
    return n, len(ids)


def embed(records):
    import boto3
    import sqlite_vec
    worth = [r for r in records if len(r["text"]) >= MIN_EMBED_CHARS]
    brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
    vecs = []
    for i in range(0, len(worth), 90):
        body = json.dumps({"texts": [r["text"][:MAX_EMBED_CHARS] for r in worth[i:i + 90]],
                           "input_type": "search_document", "truncate": "END"})
        vecs += json.loads(brt.invoke_model(modelId=EMBED_MODEL, body=body)["body"].read())["embeddings"]
        print(f"   embedded {len(vecs)}/{len(worth)}")
    db = sqlite3.connect(VEC_DB, timeout=60)
    db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
    rid = db.execute("SELECT COALESCE(MAX(rowid),0) FROM vec_meta").fetchone()[0]
    for r, v in zip(worth, vecs):
        rid += 1
        db.execute("INSERT INTO vec_meta (rowid, source, chat, date, who, sender, text, model, embed_chars) VALUES (?,?,?,?,?,?,?,?,?)",
                   (rid, r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"], EMBED_MODEL, MAX_EMBED_CHARS))
        db.execute("INSERT INTO vec_idx(rowid, embedding) VALUES (?,?)",
                   (rid, sqlite_vec.serialize_float32(v)))
    db.commit(); db.close()
    return len(vecs)


def main():
    state = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    fts = sqlite3.connect(FTS_DB, timeout=60)
    recs = collect(state)
    print(f"eligible turns in state.db: {len(recs)}")
    if "--dry-run" in sys.argv:
        return 0
    dropped, dropped_vecs = wipe(fts)
    print(f"dropped {dropped} partial records and {dropped_vecs} vectors")
    fts.executemany("INSERT INTO msgs VALUES (?,?,?,?,?,?)",
                    [(r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"])
                     for r in recs])
    fts.executemany("INSERT OR IGNORE INTO twin_chat_ingested VALUES (?)",
                    [(r["message_id"],) for r in recs])
    fts.commit()
    with open(JSONL, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps({k: v for k, v in r.items() if k != "message_id"},
                                ensure_ascii=False) + "\n")
    n = embed(recs)
    print(f"rebuilt: {len(recs)} records, {n} vectors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
