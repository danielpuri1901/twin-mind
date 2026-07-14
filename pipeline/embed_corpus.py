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


def embed(texts, input_type="search_document"):
    body = json.dumps({"texts": [t[:MAXCH] for t in texts],
                       "input_type": input_type, "truncate": "END"})
    r = brt.invoke_model(modelId=MODEL, body=body)
    return json.loads(r["body"].read())["embeddings"]


def main():
    records = []
    for path in sorted(glob.glob(os.path.join(ROOT, "normalized", "*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if len((r.get("text") or "").strip()) >= 12:   # skip empty/trivial
                records.append(r)
    print(f"embedding {len(records)} records in batches of {BATCH}...")

    if os.path.exists(DB):
        os.remove(DB)
    db = sqlite3.connect(DB)
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
            vecs = embed([r["text"] for r in chunk])
        except Exception as e:
            print(f"  batch {i}: {e} - retrying once", file=sys.stderr)
            vecs = embed([r["text"] for r in chunk])
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
    print(f"done: {n} vectors -> {DB} ({os.path.getsize(DB)/1e6:.0f} MB)")


if __name__ == "__main__":
    main()
