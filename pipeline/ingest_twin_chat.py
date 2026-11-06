"""Append the twin's own conversations to the corpus, on a timer.

Memory should not depend on a session ever ending. This reads the chat log
(shared/chat_log.py) every half hour, takes the messages it has not seen, and
appends them to the corpus. A conversation becomes searchable within the hour
whether or not the session closes, and there is nothing to restart. Until
2026-11-06 it read Hermes's state.db; everything there was drained first.

Idempotent on message id, the log line number. The ledger lives in corpus.db
so the write and its bookkeeping share one transaction.

Run with --dry-run to see what it would take without writing.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shared"))
import chat_log  # noqa: E402
import telegram_send  # noqa: E402  (its env() reads ~/.twin-mind/.env, which this unit has no EnvironmentFile for)

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
FTS_DB = os.path.join(CORPUS, "index", "corpus.db")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")
JSONL = os.path.join(CORPUS, "normalized", "twin-chat.jsonl")
EMBED_MODEL = "cohere.embed-multilingual-v3"
# Must equal shared/embedding.MAX_CHARS. Pinned by evals/test_embedding_contract.py,
# which fails if any writer drifts.
MAX_EMBED_CHARS = 2048
SOURCE = "twin-chat"
MIN_EMBED_CHARS = 12

# The twin's own scaffolding is not something anyone said. When corpus-rag
# injects context that turns out to be irrelevant, the model says so out loud,
# and that sentence was then ingested as a corpus record. Those records rank
# highly on exactly the questions that ask about the system, because they carry
# its vocabulary: on 2026-09-28 the query "what did we decide about moving the
# corpus to s3" returned two of them in its top five.
#
# Only 37 records, 1.9% of twin-chat, so this is precision rather than volume.
# The pattern is anchored to the opening of the message because the phrase only
# means boilerplate when the message BEGINS with it; quoting it mid-answer is a
# real answer about how the system behaves.
TWIN_BOILERPLATE = re.compile(
    r"^\W*(the )?corpus( context)? (is\s+not|is\s?n'?t|was\s+not|was\s?n'?t)\s+relevant", re.I)


def is_boilerplate(role: str, text: str) -> bool:
    return role == "assistant" and bool(TWIN_BOILERPLATE.match((text or "").strip()))


def ensure_ledger(fts):
    fts.execute("CREATE TABLE IF NOT EXISTS twin_chat_ingested (message_id INTEGER PRIMARY KEY)")
    fts.commit()


def pending(messages, fts):
    """Messages worth keeping that the ledger has not seen."""
    done = {r[0] for r in fts.execute("SELECT message_id FROM twin_chat_ingested")}
    out = []
    for message in messages:
        if message["id"] in done:
            continue
        role, text = message.get("role"), (message.get("text") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        if is_boilerplate(role, text):
            continue
        try:
            date = datetime.fromtimestamp(float(message.get("ts")), timezone.utc).isoformat()
        except (TypeError, ValueError):
            date = str(message.get("ts"))[:32]
        out.append({"message_id": message["id"], "source": SOURCE, "chat": "twin", "date": date,
                    "who": "me" if role == "user" else "twin",
                    "sender": "Daniel" if role == "user" else "Twin Mind",
                    "text": text, "session_id": message.get("conversation_id")})
    return out


def chat_pairs(recs):
    """(user text, assistant text) for each user message directly followed by an assistant reply.
    ponytail: a user message whose reply lands in the next run gets no trace; fine at a 30-minute cadence."""
    return [(a["text"], b["text"]) for a, b in zip(recs, recs[1:]) if a["who"] == "me" and b["who"] == "twin"]


def send_traces(recs):
    """One Langfuse trace per exchange. No keys: silent no-op. Any failure: one stderr line, ingest goes on."""
    try:
        keys = {n: telegram_send.env(f"HERMES_LANGFUSE_{n}") for n in ("PUBLIC_KEY", "SECRET_KEY", "BASE_URL")}
    except OSError:
        return
    pairs = chat_pairs(recs)
    if not (keys["PUBLIC_KEY"] and keys["SECRET_KEY"] and pairs):
        return
    lf = None
    try:
        for n, v in keys.items():
            if v:
                os.environ[f"LANGFUSE_{n}"] = v
        from langfuse import get_client, propagate_attributes
        lf = get_client()
        for question, answer in pairs:
            with propagate_attributes(session_id="chat", tags=["agent:chat", "env:prod"]):
                with lf.start_as_current_observation(name="chat", input=question, output=answer):
                    lf.set_current_trace_io(input=question, output=answer)
        print(f"langfuse: {len(pairs)} chat traces sent")
    except Exception as e:
        print(f"langfuse: chat traces not sent ({type(e).__name__}: {str(e)[:120]})", file=sys.stderr)
    finally:
        try:
            if lf:
                lf.flush()
        except Exception:
            pass


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
        body = json.dumps({"texts": [r["text"][:MAX_EMBED_CHARS] for r in worth[i:i + 90]],
                           "input_type": "search_document", "truncate": "END"})
        vecs += json.loads(brt.invoke_model(modelId=EMBED_MODEL, body=body)["body"].read())["embeddings"]
    db = sqlite3.connect(VEC_DB, timeout=30)
    try:
        db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
        rid = db.execute("SELECT COALESCE(MAX(rowid),0) FROM vec_meta").fetchone()[0]
        for r, v in zip(worth, vecs):
            rid += 1
            db.execute("INSERT INTO vec_meta (rowid, source, chat, date, who, sender, text, model, embed_chars) VALUES (?,?,?,?,?,?,?,?,?)",
                       (rid, r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"], EMBED_MODEL, MAX_EMBED_CHARS))
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

    fts = sqlite3.connect(FTS_DB, timeout=30)
    ensure_ledger(fts)

    recs = pending(chat_log.read(), fts)
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

    send_traces(recs)  # before embed: a Bedrock failure must not lose the traces, the ledger already has these rows
    n = embed(recs)
    print(f"appended {len(recs)} records, embedded {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
