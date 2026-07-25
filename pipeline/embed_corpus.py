#!/usr/bin/env python3
"""
embed_corpus.py - embed all normalized records with Cohere Embed Multilingual v3
(Bedrock, eu-west-1) into a local sqlite-vec file. One-off ~$0.3-0.5; rebuildable.

Output: ~/twin-corpus/index/vectors.db
  - vec_meta(rowid, source, chat, date, who, sender, text)
  - vec_idx: vec0 virtual table, embedding float[1024], rowid-aligned with vec_meta
"""
import glob
import json
import os
import sqlite3
import sys

import boto3
import sqlite_vec

ROOT = os.environ.get("TWIN_CORPUS", os.path.expanduser("~/twin-corpus"))
DB = os.path.join(ROOT, "index", "vectors.db")
MODEL = "cohere.embed-multilingual-v3"
BATCH = 96          # Cohere max texts per call
MAXCH = 1500        # truncate long records (emails)

brt = boto3.client("bedrock-runtime", region_name="eu-west-1")


def embed(texts, input_type="search_document", maxch=MAXCH):
    body = json.dumps({"texts": [t[:maxch] for t in texts],
                       "input_type": input_type, "truncate": "END"})
    r = brt.invoke_model(modelId=MODEL, body=body)
    return json.loads(r["body"].read())["embeddings"]


def _connect():
    db = sqlite3.connect(DB)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def embed_only(meeting):
    """Incrementally embed ONE meeting's records into the EXISTING vectors.db - no rebuild.
    Idempotent upsert: drop any prior rows for this meeting (so a re-run or an updated
    transcript replaces cleanly), then append with fresh rowids. Cost is a handful of Cohere
    calls for one meeting, not a full re-embed of the whole corpus."""
    if not os.path.exists(DB):
        print(f"vectors.db missing - run a full build first"); return 0
    src = os.path.join(ROOT, "normalized", "transcripts.jsonl")
    recs = [r for r in (json.loads(l) for l in open(src, encoding="utf-8"))
            if r.get("meeting", r.get("chat", "")) == meeting and len((r.get("text") or "").strip()) >= 12]
    if not recs:
        print(f"no records for meeting '{meeting}' in {src}"); return 0
    db = _connect()
    old = [row[0] for row in db.execute("SELECT rowid FROM vec_meta WHERE chat=?", (meeting,)).fetchall()]
    for rid in old:  # remove prior rows from BOTH aligned tables (idempotent upsert)
        db.execute("DELETE FROM vec_meta WHERE rowid=?", (rid,))
        db.execute("DELETE FROM vec_idx WHERE rowid=?", (rid,))
    rid = db.execute("SELECT COALESCE(MAX(rowid),0) FROM vec_meta").fetchone()[0]
    n = 0
    for i in range(0, len(recs), BATCH):
        chunk = recs[i:i + BATCH]
        try:
            vecs = embed([r["text"] for r in chunk])
        except Exception as e:
            print(f"  batch {i}: {e} - retrying once", file=sys.stderr)
            vecs = embed([r["text"] for r in chunk])
        for r, v in zip(chunk, vecs):
            rid += 1; n += 1
            db.execute("INSERT INTO vec_meta VALUES (?,?,?,?,?,?,?)",
                       (rid, r.get("source", ""), meeting, r.get("date", ""),
                        r.get("who", ""), r.get("sender", ""), r.get("text", "")))
            db.execute("INSERT INTO vec_idx(rowid, embedding) VALUES (?, ?)",
                       (rid, sqlite_vec.serialize_float32(v)))
    db.commit()
    print(f"incremental embed '{meeting}': removed {len(old)} old, appended {n} vectors -> {DB}")
    return n


def load_records(paths):
    """Read normalized jsonl paths into records, skipping empty/trivial (<12-char) text."""
    records = []
    for path in paths:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if len((r.get("text") or "").strip()) >= 12:
                records.append(r)
    return records


def build(records, out_db=DB, maxch=MAXCH):
    """Full (re)build: create the two aligned tables in out_db and embed every record. Used by
    main() for production (normalized/ -> vectors.db) and by the retrieval eval for a scratch
    index (e.g. normalized-windowed/ -> vectors-windowed.db). Deletes out_db first."""
    print(f"embedding {len(records)} records in batches of {BATCH} -> {out_db} (maxch={maxch})...")
    os.makedirs(os.path.dirname(out_db), exist_ok=True)
    if os.path.exists(out_db):
        os.remove(out_db)
    db = sqlite3.connect(out_db)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.execute("CREATE TABLE vec_meta(rowid INTEGER PRIMARY KEY, source TEXT, "
               "chat TEXT, date TEXT, who TEXT, sender TEXT, text TEXT)")
    db.execute("CREATE VIRTUAL TABLE vec_idx USING vec0(embedding float[1024])")

    n = 0
    for i in range(0, len(records), BATCH):
        chunk = records[i:i + BATCH]
        try:
            vecs = embed([r["text"] for r in chunk], maxch=maxch)
        except Exception as e:
            print(f"  batch {i}: {e} - retrying once", file=sys.stderr)
            vecs = embed([r["text"] for r in chunk], maxch=maxch)
        for r, v in zip(chunk, vecs):
            n += 1
            db.execute("INSERT INTO vec_meta VALUES (?,?,?,?,?,?,?)",
                       (n, r.get("source", ""), r.get("chat", r.get("meeting", "")),
                        r.get("date", ""), r.get("who", ""), r.get("sender", ""),
                        r.get("text", "")))
            db.execute("INSERT INTO vec_idx(rowid, embedding) VALUES (?, ?)",
                       (n, sqlite_vec.serialize_float32(v)))
        if (i // BATCH) % 20 == 0:
            db.commit()
            print(f"  {n}/{len(records)}")
    db.commit()
    print(f"done: {n} vectors -> {out_db} ({os.path.getsize(out_db)/1e6:.0f} MB)")
    return n


def main():
    paths = sorted(glob.glob(os.path.join(ROOT, "normalized", "*.jsonl")))
    build(load_records(paths), DB, MAXCH)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="incrementally embed ONE meeting (by its stem) into the existing db, no rebuild")
    ap.add_argument("--inputs", nargs="+", help="explicit jsonl paths to embed (instead of normalized/*.jsonl); pairs with --out")
    ap.add_argument("--out", default=DB, help="output vectors db path (default: index/vectors.db)")
    ap.add_argument("--maxch", type=int, default=MAXCH, help="per-record char cap before embedding (default 1500)")
    a = ap.parse_args()
    if a.only:
        embed_only(a.only)
    elif a.inputs:
        build(load_records(a.inputs), a.out, a.maxch)
    else:
        main()
