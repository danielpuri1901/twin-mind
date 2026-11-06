"""The full sync must never replace a good S3 backup with an empty one.

From 2026-09-29 to 2026-10-22 the state.db snapshot failed on every run (the
staging copy overflowed the box's 924 MB /tmp tmpfs), left a 0-byte file in
staging, and the sync uploaded it over the real backup while the unit reported
success. These tests pin the fix: a failed snapshot stops the upload, staging
is not in /tmp, and a SQLite rollback journal that vanishes mid-copy is never
copied.
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
import corpus_sync as cs  # noqa: E402


def make_corpus(bad_db: bool):
    root = tempfile.mkdtemp()
    corpus = os.path.join(root, "twin-corpus")
    os.makedirs(os.path.join(corpus, "index"))
    db = sqlite3.connect(os.path.join(corpus, "index", "corpus.db"))
    db.execute("CREATE TABLE t(x)")
    db.commit()
    db.close()
    open(os.path.join(corpus, "index", "corpus.db-journal"), "w").close()
    if bad_db:
        with open(os.path.join(corpus, "index", "broken.db"), "w") as f:
            f.write("not a database")
    return root, corpus


def run_main(corpus):
    """main() with the upload recorded instead of sent."""
    uploads, staged = [], {}

    def fake_upload(src, dest):
        uploads.append(src)
        staged["files"] = sorted(os.path.relpath(os.path.join(d, n), src)
                                 for d, _, ns in os.walk(src) for n in ns)
        return 0

    cs.CORPUS, cs.BUCKET, cs.KMS_KEY = corpus, "bucket", "key"
    cs.STATE_DB = os.path.join(corpus, "no-state.db")
    cs.upload = fake_upload
    sys.argv = ["corpus_sync.py"]
    return cs.main(), uploads, staged.get("files", [])


def test_failed_snapshot_blocks_the_upload():
    _, corpus = make_corpus(bad_db=True)
    rc, uploads, _ = run_main(corpus)
    assert rc == 1
    assert uploads == []


def test_clean_run_uploads_from_disk_not_tmp_and_skips_the_journal():
    root, corpus = make_corpus(bad_db=False)
    rc, uploads, files = run_main(corpus)
    assert rc == 0
    assert len(uploads) == 1
    assert os.path.dirname(uploads[0]) == root
    assert "index/corpus.db" in files
    assert "index/corpus.db-journal" not in files


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
            passed += 1
    print(f"\n{passed} passed")
