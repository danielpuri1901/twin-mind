"""Recompute every vector at the shared 2,048 character cap.

THE PROBLEM

Two code paths cut long records at different lengths before embedding them.
The full build used 1,500 characters, every incremental writer used 2,048. So
a record over 1,500 characters got a different vector depending on whether the
30-minute timer or a rebuild created it. Measured 2026-09-29: 2,808 of 8,366
vectors are over 1,500 characters, and 1,749 sit in the window where the two
caps actually differ. Traced one real 1,607-character transcript through both
and the vectors differed in 1,021 of 1,024 dimensions, cosine distance 0.0055.

Small, but in a KNN over 8,366 vectors near-neighbours are routinely closer
together than that, so ranking depended on provenance rather than on meaning.

WHY THIS READS THE DATABASE AND NOT THE JSONL

The obvious rebuild is `python embed_corpus.py`, and it would be a disaster.
The production index was never built from `normalized/*.jsonl`: that glob
yields 29,812 records against the live index's 8,366, because the box holds
three input trees (normalized, normalized-windowed, normalized-windowed-ctx)
and the live index is a mix of them, plus twin-chat and meeting records that
exist only as timer appends and are in no input file at all. The glob would
also re-ingest gmail-noise-removed-20260928.jsonl, resurrecting the 2,415
machine-mail records that were deliberately purged.

`vec_meta.text` already holds the exact, untruncated text of every embedded
record. Truncation only ever happened in the API call, never in storage. So
the index is its own best input: same records, same rowids, same metadata,
and only the numbers change.

RESUMABLE, BECAUSE IT IS METERED WORK

`vec_meta.embed_chars` records the cap each row was embedded at. Rows are
selected by `embed_chars IS NULL OR embed_chars != target`, so a crash or an
interrupt leaves a half-migrated index that is still correct (every row's
vector matches its stamp) and the next run finishes the rest. It also makes
this class of drift visible in the DATA, not only in the source: the `model`
column could never have caught it, because the model never changed.

    reembed-at-2048 --dry-run      # what would change, no calls
    reembed-at-2048                # do it
    reembed-at-2048 --verify       # confirm afterwards
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")


def connect(path, read_only=False):
    import sqlite3
    import sqlite_vec
    uri = f"file:{path}?mode=ro" if read_only else path
    db = sqlite3.connect(uri, uri=read_only, timeout=60)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def ensure_column(db):
    cols = {r[1] for r in db.execute("pragma table_info(vec_meta)")}
    if "embed_chars" not in cols:
        db.execute("ALTER TABLE vec_meta ADD COLUMN embed_chars INTEGER")
        db.commit()
        return True
    return False


def pending(db, target):
    return db.execute(
        "SELECT rowid, text FROM vec_meta "
        "WHERE embed_chars IS NULL OR embed_chars != ? ORDER BY rowid",
        (target,)).fetchall()


def main():
    from shared.embedding import BATCH, MAX_CHARS, MODEL, embed_body

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=VEC_DB)
    ap.add_argument("--target", type=int, default=MAX_CHARS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="stop after N rows (for a trial run)")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"no vector index at {args.db}", file=sys.stderr)
        return 1

    if args.verify:
        db = connect(args.db, read_only=True)
        total = db.execute("SELECT count(*) FROM vec_meta").fetchone()[0]
        idx = db.execute("SELECT count(*) FROM vec_idx").fetchone()[0]
        print(f"vec_meta rows   {total}")
        print(f"vec_idx rows    {idx}   {'aligned' if idx == total else 'MISALIGNED'}")
        print("\nembed_chars distribution:")
        for value, n in db.execute(
                "SELECT coalesce(embed_chars, -1), count(*) FROM vec_meta GROUP BY 1 ORDER BY 2 DESC"):
            label = "(not stamped)" if value == -1 else str(value)
            print(f"  {label:<16} {n:>7}")
        left = db.execute("SELECT count(*) FROM vec_meta WHERE embed_chars IS NULL "
                          "OR embed_chars != ?", (args.target,)).fetchone()[0]
        print(f"\n{'COMPLETE' if left == 0 else str(left) + ' rows still to do'}")
        return 0

    db = connect(args.db, read_only=args.dry_run)
    if args.dry_run:
        # A dry run must not touch the schema. Without the column every row is
        # pending by definition, which is the same answer ensure_column would
        # have produced, without writing anything.
        cols = {r[1] for r in db.execute("pragma table_info(vec_meta)")}
        rows = (pending(db, args.target) if "embed_chars" in cols
                else db.execute("SELECT rowid, text FROM vec_meta ORDER BY rowid").fetchall())
    else:
        if ensure_column(db):
            print("added column: vec_meta.embed_chars")
        rows = pending(db, args.target)
    if args.limit:
        rows = rows[:args.limit]
    total = db.execute("SELECT count(*) FROM vec_meta").fetchone()[0]
    changed = sum(1 for _r, t in rows if len(t or "") > 1500)
    print(f"index      {args.db}")
    print(f"rows       {total} total, {len(rows)} to re-embed at {args.target} chars")
    print(f"of those   {changed} are over 1500 chars, so their vector will actually move")
    print(f"calls      ~{-(-len(rows) // BATCH)} Bedrock requests at {BATCH} texts each")

    if args.dry_run:
        print("\ndry run. Nothing called, nothing written.")
        return 0
    if not rows:
        print("\nnothing to do.")
        return 0

    import boto3
    import sqlite_vec
    brt = boto3.client("bedrock-runtime", region_name="eu-west-1")

    done, started = 0, time.time()
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        body = embed_body([t for _r, t in chunk], max_chars=args.target)
        try:
            payload = brt.invoke_model(modelId=MODEL, body=body)["body"].read()
        except Exception as exc:
            print(f"\nbatch at row {chunk[0][0]} failed: {exc}", file=sys.stderr)
            print(f"{done} rows committed and stamped; re-run to continue from there.",
                  file=sys.stderr)
            return 1
        vecs = json.loads(payload)["embeddings"]

        # One transaction per batch: a crash leaves every committed row's vector
        # matching its stamp, so the index is never in a state nobody can read.
        with db:
            for (rowid, _text), v in zip(chunk, vecs):
                db.execute("DELETE FROM vec_idx WHERE rowid = ?", (rowid,))
                db.execute("INSERT INTO vec_idx(rowid, embedding) VALUES (?,?)",
                           (rowid, sqlite_vec.serialize_float32(v)))
                db.execute("UPDATE vec_meta SET embed_chars = ?, model = ? WHERE rowid = ?",
                           (args.target, MODEL, rowid))
        done += len(chunk)
        if (i // BATCH) % 10 == 0 or done == len(rows):
            rate = done / max(time.time() - started, 0.001)
            print(f"  {done}/{len(rows)}  ({rate:.0f} rows/s)")

    left = db.execute("SELECT count(*) FROM vec_meta WHERE embed_chars IS NULL "
                      "OR embed_chars != ?", (args.target,)).fetchone()[0]
    idx = db.execute("SELECT count(*) FROM vec_idx").fetchone()[0]
    # Re-read rather than reusing the count from before the work. The ingest
    # timer runs every 30 minutes and this takes ~90 seconds, so rows can and
    # do arrive mid-run; comparing a fresh vec_idx against a stale vec_meta
    # reported MISALIGNED on a perfectly healthy index the first time.
    meta = db.execute("SELECT count(*) FROM vec_meta").fetchone()[0]
    arrived = meta - total
    print(f"\nre-embedded {done} rows in {time.time() - started:.0f}s")
    if arrived:
        print(f"{arrived} row(s) arrived from the ingest timer while this ran")
    print(f"vec_idx {idx}, vec_meta {meta}: "
          f"{'aligned' if idx == meta else 'MISALIGNED - investigate'}")
    print(f"{left} rows remain at another cap")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
