#!/usr/bin/env python3
"""
build_index.py - build the SQLite FTS5 index over normalized corpus records.
Consumed only through the corpus-search contract (shared/corpus_search.py).
"""
import glob
import json
import os
import sqlite3

ROOT = os.environ.get("TWIN_CORPUS", os.path.expanduser("~/twin-corpus"))
DB = os.path.join(ROOT, "index", "corpus.db")


def build(inputs=None, out_db=DB):
    """(Re)build the FTS5 index. Default: all normalized/*.jsonl -> corpus.db (production). The
    retrieval eval / promotion passes explicit inputs (windowed+contextual) + a candidate out_db."""
    if inputs is None:
        inputs = sorted(glob.glob(os.path.join(ROOT, "normalized", "*.jsonl")))
    os.makedirs(os.path.dirname(out_db), exist_ok=True)
    db = sqlite3.connect(out_db)
    db.execute("DROP TABLE IF EXISTS msgs")
    db.execute("CREATE VIRTUAL TABLE msgs USING fts5(source, chat, date, who, sender, text)")
    n = 0
    for path in inputs:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            db.execute("INSERT INTO msgs VALUES (?,?,?,?,?,?)",
                       (r.get("source", ""), r.get("chat", r.get("meeting", "")),
                        r.get("date", ""), r.get("who", ""), r.get("sender", ""),
                        r.get("text", "")))
            n += 1
    db.commit()
    print(f"indexed {n} records -> {out_db}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", help="explicit jsonl paths (default: normalized/*.jsonl)")
    ap.add_argument("--out", default=DB, help="output FTS db path (default: index/corpus.db)")
    a = ap.parse_args()
    build(a.inputs, a.out)
