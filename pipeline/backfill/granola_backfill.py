"""One-off backfill of the Granola meetings the corpus never received.

Granola kept recording after the corpus stopped hearing it: the `transcript`
source ends 2026-06-29, while Granola holds 8 meetings between 2026-08-26 and
2026-09-23, including the Kavak conversations, the Invopop screening and the
Oneleet exploratory.

Content comes from the Granola MCP (only reachable from Daniel's Claude
session, not from the box), so it is carried in this file rather than fetched
here. Record shape, chunk size and the text prefix match what
ingest_wispr_meetings.py writes, so these are indistinguishable from natively
ingested meetings. Idempotent: re-running inserts nothing.
"""

import json
import os
import re
import sqlite3
import sys

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
FTS_DB = os.path.join(CORPUS, "index", "corpus.db")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")
JSONL = os.path.join(CORPUS, "normalized", "transcripts.jsonl")
EMBED_MODEL = "cohere.embed-multilingual-v3"
# Must equal shared/embedding.MAX_CHARS. Pinned by evals/test_embedding_contract.py,
# which fails if any writer drifts.
MAX_EMBED_CHARS = 2048
SOURCE = "transcript"
CHUNK = 1800

MEETINGS = json.load(open(os.path.join(os.path.dirname(__file__), "granola_meetings.json")))


def slug(title, date):
    s = re.sub(r"[^a-z0-9]+", "-", (title or "untitled").lower()).strip("-")
    return f"{date[:10]}-{s}"[:80]


def chunks(text, chat, date):
    """Split on section headings, then pack to CHUNK chars. Mirrors the Wispr
    ingester: a whole section per vector where possible, hard-split only when
    one section is oversized."""
    prefix = f"[{chat} · {date[:10]}] "
    parts, buf = [], ""
    for block in re.split(r"\n(?=#{1,4} )", text.strip()):
        block = block.strip()
        if not block:
            continue
        if len(block) > CHUNK:
            if buf:
                parts.append(buf); buf = ""
            for i in range(0, len(block), CHUNK):
                parts.append(block[i:i + CHUNK])
            continue
        if len(buf) + len(block) + 1 > CHUNK:
            parts.append(buf); buf = block
        else:
            buf = (buf + "\n" + block).strip()
    if buf:
        parts.append(buf)
    return [prefix + p for p in parts]


def build():
    recs = []
    for m in MEETINGS:
        chat = slug(m["title"], m["date"])
        for text in chunks(m["summary"], chat, m["date"]):
            recs.append({"source": SOURCE, "chat": chat, "date": m["date"],
                         "who": "summary", "sender": "", "text": text})
    return recs


def already(conn, chats):
    have = set()
    for c in chats:
        if conn.execute("select 1 from msgs where source=? and chat=? limit 1",
                        (SOURCE, c)).fetchone():
            have.add(c)
    return have


def main():
    recs = build()
    chats = {r["chat"] for r in recs}
    fts = sqlite3.connect(FTS_DB)
    have = already(fts, chats)
    recs = [r for r in recs if r["chat"] not in have]
    print(f"meetings: {len(chats)}, already present: {len(have)}, records to add: {len(recs)}")
    if not recs:
        fts.close()
        return 0

    fts.executemany("INSERT INTO msgs VALUES (?,?,?,?,?,?)",
                    [(r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"])
                     for r in recs])
    fts.commit(); fts.close()

    with open(JSONL, "a", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    import boto3
    import sqlite_vec
    brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
    vecs = []
    for i in range(0, len(recs), 90):
        body = json.dumps({"texts": [r["text"][:MAX_EMBED_CHARS] for r in recs[i:i + 90]],
                           "input_type": "search_document", "truncate": "END"})
        vecs += json.loads(brt.invoke_model(modelId=EMBED_MODEL, body=body)["body"].read())["embeddings"]
    db = sqlite3.connect(VEC_DB)
    db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
    rid = db.execute("SELECT COALESCE(MAX(rowid),0) FROM vec_meta").fetchone()[0]
    for r, v in zip(recs, vecs):
        rid += 1
        db.execute("INSERT INTO vec_meta (rowid, source, chat, date, who, sender, text, model, embed_chars) VALUES (?,?,?,?,?,?,?,?,?)",
                   (rid, r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"], EMBED_MODEL, MAX_EMBED_CHARS))
        db.execute("INSERT INTO vec_idx(rowid, embedding) VALUES (?,?)",
                   (rid, sqlite_vec.serialize_float32(v)))
    db.commit(); db.close()
    print(f"inserted {len(recs)} records and {len(vecs)} vectors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
