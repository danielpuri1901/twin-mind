"""Sync the box's corpus to S3, without ever uploading a torn database.

The box holds the canonical corpus. S3 is the durable copy: the box's root
volume has DeleteOnTermination true, so before this existed one terminate
would have destroyed every record the twin had.

The detail that matters: corpus.db is written while the twin runs. Copying a
live SQLite file byte by byte can capture a half-written page and produce a
database that opens fine and is quietly corrupt. So every .db is snapshotted
through SQLite's own backup API, which takes a consistent point-in-time copy
under the database's own locking, and the snapshot is what gets uploaded.

TWO LANES, because the corpus is 21 MB of irreplaceable data sitting next to
761 MB of derived data, and putting both on one schedule means choosing a
period that is wrong for one of them.

  --fast   normalized/*.jsonl only, every 15 minutes. These are append-only
           and are the ONLY copy of what was said; an index can be rebuilt
           from them, they cannot be rebuilt from anything. ~21 MB total and
           a few MB per run, so the period can be short.

  full     the whole tree, every 6 hours: the jsonl again plus the indexes
           and a snapshot of the Hermes session store. 761 MB of that is
           corpus.db and vectors.db, which are derived. Losing them costs one
           FTS rebuild (free) and one re-embed (about 87 Cohere calls, which
           the repo puts at $0.30 to $0.50). Losing a jsonl costs records
           that never come back.

Before this split the sync ran every 6 hours while ingest ran every 30
minutes, so up to twelve ingest cycles of conversation existed on exactly one
EBS volume. Now the worst case for a brand new message is one ingest period
plus one fast sync, about 45 minutes, and for anything already ingested it is
15 minutes.

The fast lane syncs one subtree to the matching subtree, so --delete there
cannot reach the index objects. Pointing --delete at the bucket root from a
partial tree would delete the indexes from S3, which is the obvious way to
turn a backup improvement into data loss.

Run from a timer. Exit code is non-zero only when the upload itself fails,
so a genuine failure surfaces as a unit failure.
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
# The bucket name carries the AWS account id and the key id names a private
# key, so neither has a default here: this repo is public. On the box a
# systemd drop-in sets both for the two sync timers; .env.example lists them.
BUCKET = os.environ.get("TWIN_CORPUS_BUCKET", "")
PREFIX = os.environ.get("TWIN_CORPUS_PREFIX", "box")
KMS_KEY = os.environ.get("TWIN_CORPUS_KMS_KEY", "")
STATE_DB = os.environ.get("HERMES_STATE_DB") or os.path.expanduser("~/.hermes/state.db")


def upload(src: str, dest: str) -> int:
    cmd = ["aws", "s3", "sync", src, dest,
           "--sse", "aws:kms", "--sse-kms-key-id", KMS_KEY,
           "--delete", "--only-show-errors"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        # The CLI writes "upload failed", which does not contain the word
        # "error"; an earlier check grepped for "error" and reported success
        # while two files had failed. Trust the exit code.
        print(result.stderr[-800:], file=sys.stderr)
    return result.returncode


# Both record trees. normalized/ is what the ingesters append to;
# normalized-canonical/ is exported FROM the index and is the only copy of the
# 1,679 records that exist nowhere else (all 526 meetings, and most of
# twin-chat). Backing up one and not the other would leave exactly the gap this
# was built to close.
FAST_TREES = ("normalized", "normalized-canonical")


def fast() -> int:
    """The append-only tier. Small, frequent, and the only copy that matters."""
    rc = 0
    for tree in FAST_TREES:
        src = os.path.join(CORPUS, tree)
        if not os.path.isdir(src):
            print(f"skipping {tree}: not present", file=sys.stderr)
            continue
        dest = f"s3://{BUCKET}/{PREFIX}/{tree}/"
        code = upload(src + "/", dest)
        if code == 0:
            n = sum(1 for f in os.listdir(src) if f.endswith(".jsonl"))
            print(f"fast sync ok: {tree}, {n} jsonl files -> {dest}")
        rc = rc or code
    return rc


def snapshot_one(src: str, dst: str) -> bool:
    """One consistent point-in-time copy through SQLite's backup API."""
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        target = sqlite3.connect(dst)
        with target:
            source.backup(target)
        source.close()
        target.close()
        return True
    except Exception as exc:
        print(f"snapshot failed for {src}: {exc}", file=sys.stderr)
        return False


def snapshot_databases(staging: str) -> list:
    """Copy the tree into staging, replacing every .db with a consistent snapshot."""
    shutil.copytree(
        CORPUS, staging,
        ignore=shutil.ignore_patterns("*.db", "*.db-wal", "*.db-shm", ".git"),
        dirs_exist_ok=True,
    )
    snapped = []
    for root, _dirs, files in os.walk(CORPUS):
        if ".git" in root:
            continue
        for name in files:
            if not name.endswith(".db"):
                continue
            src = os.path.join(root, name)
            rel = os.path.relpath(src, CORPUS)
            dst = os.path.join(staging, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if snapshot_one(src, dst):
                snapped.append(rel)

    # The Hermes session store lives outside the corpus tree and was not backed
    # up at all. It holds every message for the window between arriving and
    # being ingested, so without it that window has exactly one copy.
    if os.path.exists(STATE_DB):
        if snapshot_one(STATE_DB, os.path.join(staging, "hermes", "state.db")):
            snapped.append("hermes/state.db")
    return snapped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fast", action="store_true",
                        help="normalized/*.jsonl only; safe to run every 15 minutes")
    args = parser.parse_args()

    if not BUCKET or not KMS_KEY:
        print("TWIN_CORPUS_BUCKET and TWIN_CORPUS_KMS_KEY must be set; see .env.example",
              file=sys.stderr)
        return 1
    if not os.path.isdir(CORPUS):
        print(f"no corpus at {CORPUS}", file=sys.stderr)
        return 1
    if args.fast:
        return fast()

    staging = tempfile.mkdtemp(prefix="corpus-sync-")
    try:
        snapped = snapshot_databases(staging)
        print(f"snapshotted {len(snapped)} databases: {', '.join(snapped) or 'none'}")
        rc = upload(staging, f"s3://{BUCKET}/{PREFIX}/")
        if rc == 0:
            print(f"synced {CORPUS} to s3://{BUCKET}/{PREFIX}/")
        return rc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
