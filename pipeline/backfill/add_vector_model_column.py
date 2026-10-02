"""Add `model` to vec_meta and stamp the existing rows.

Nothing recorded which embedder produced a vector. That is fine until the day
the model changes, and on that day there is no way to tell a re-embedded row
from a stale one, so the only safe response to any model change is to rebuild
all of it. One text column removes that.

It also makes a partial re-embed possible, which matters for the contextual
headers change: that one has to re-embed everything once, and a run that dies
halfway through currently leaves an index nobody can reason about.

Every existing row is stamped cohere.embed-multilingual-v3, which is true:
that is the only embedder this corpus has ever used, and every writer
(embed_corpus, ingest_twin_chat, ingest_wispr_meetings, twin-episodic) names
it as a constant.

Idempotent. Running it twice is a no-op. Read the state first with --check.
"""

import argparse
import os
import sqlite3
import sys

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")
MODEL = "cohere.embed-multilingual-v3"


def columns(db):
    return {r[1] for r in db.execute("pragma table_info(vec_meta)")}


def report(db):
    total = db.execute("select count(*) from vec_meta").fetchone()[0]
    print(f"vec_meta rows: {total}")
    if "model" not in columns(db):
        print("model column: absent")
        return
    print("model column: present")
    for model, n in db.execute(
            "select coalesce(model,'(null)'), count(*) from vec_meta "
            "group by 1 order by 2 desc"):
        print(f"  {model:<34} {n:>7}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=VEC_DB)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--check", action="store_true", help="report state, change nothing")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"no vector index at {args.db}", file=sys.stderr)
        return 1

    if args.check:
        db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        try:
            report(db)
        finally:
            db.close()
        return 0

    db = sqlite3.connect(args.db, timeout=30)
    try:
        if "model" not in columns(db):
            db.execute("ALTER TABLE vec_meta ADD COLUMN model TEXT")
            print("added column: vec_meta.model")
        else:
            print("column already present")
        n = db.execute("update vec_meta set model = ? where model is null",
                       (args.model,)).rowcount
        db.commit()
        print(f"stamped {n} rows with {args.model}")
        report(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
