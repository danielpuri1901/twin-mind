#!/usr/bin/env python3
"""
build_index.py - build the SQLite FTS5 index over normalized corpus records.
Consumed only through the corpus-search contract (tools/corpus_search.py).
"""
import glob
import json
import os
import sqlite3

ROOT = os.environ.get("TWIN_CORPUS", os.path.expanduser("~/twin-corpus"))
DB = os.path.join(ROOT, "index", "corpus.db")


def build():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("DROP TABLE IF EXISTS msgs")
    db.execute("CREATE VIRTUAL TABLE msgs USING fts5(source, chat, date, who, sender, text)")
    n = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "normalized", "*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            db.execute("INSERT INTO msgs VALUES (?,?,?,?,?,?)",
                       (r.get("source", ""), r.get("chat", r.get("meeting", "")),
                        r.get("date", ""), r.get("who", ""), r.get("sender", ""),
                        r.get("text", "")))
            n += 1
    db.commit()
    print(f"indexed {n} records -> {DB}")


if __name__ == "__main__":
    build()
