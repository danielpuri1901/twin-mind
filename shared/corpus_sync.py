"""Sync the box's corpus to S3, without ever uploading a torn database.

The box holds the canonical corpus. S3 is the durable copy: the box's root
volume has DeleteOnTermination true, so before this existed one terminate
would have destroyed every record the twin had.

The detail that matters: corpus.db is written while the twin runs. Copying a
live SQLite file byte by byte can capture a half-written page and produce a
database that opens fine and is quietly corrupt. So every .db is snapshotted
through SQLite's own backup API, which takes a consistent point-in-time copy
under the database's own locking, and the snapshot is what gets uploaded.

Run from a timer. Exit code is non-zero only when the upload itself fails,
so a genuine failure surfaces as a unit failure.
"""

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
            try:
                source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
                target = sqlite3.connect(dst)
                with target:
                    source.backup(target)
                source.close()
                target.close()
                snapped.append(rel)
            except Exception as exc:
                print(f"snapshot failed for {rel}: {exc}", file=sys.stderr)
    return snapped


def main() -> int:
    if not BUCKET or not KMS_KEY:
        print("TWIN_CORPUS_BUCKET and TWIN_CORPUS_KMS_KEY must be set; see .env.example",
              file=sys.stderr)
        return 1
    if not os.path.isdir(CORPUS):
        print(f"no corpus at {CORPUS}", file=sys.stderr)
        return 1
    staging = tempfile.mkdtemp(prefix="corpus-sync-")
    try:
        snapped = snapshot_databases(staging)
        print(f"snapshotted {len(snapped)} databases: {', '.join(snapped) or 'none'}")
        result = subprocess.run(
            ["aws", "s3", "sync", staging, f"s3://{BUCKET}/{PREFIX}/",
             "--sse", "aws:kms", "--sse-kms-key-id", KMS_KEY,
             "--delete", "--only-show-errors"],
            capture_output=True, text=True, timeout=3600,
        )
        if result.returncode != 0:
            print(result.stderr[-800:], file=sys.stderr)
            return result.returncode
        print(f"synced {CORPUS} to s3://{BUCKET}/{PREFIX}/")
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
