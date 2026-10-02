"""Export the live index back to jsonl, so the corpus can be rebuilt from files.

THE PROBLEM THIS SOLVES

The index is not reproducible from any input tree, and worse, some of it exists
nowhere else. Reconciled by text against every candidate file on 2026-09-29:

    contacts, gchat, imessage   100%   normalized-windowed-ctx/
    gcal, gmail, transcript     96-98% normalized-windowed-ctx/
    twin-chat                   39.7%  normalized/twin-chat.jsonl
    meeting                     0%     NO FILE AT ALL

1,679 records live only inside vectors.db. The jsonl tree is described
everywhere in this repo as "the durable copy" and for those records it is not:
an index rebuild would silently drop them, and losing the file loses them
outright. `normalized/` also holds the gmail purge restore file and pre-window
originals, so a naive `embed_corpus.py` run yields 29,812 records against the
live 8,370.

WHY vec_meta IS THE RIGHT SOURCE

It stores each record's full untruncated text alongside source, chat, date, who
and sender: everything the record shape needs. Truncation only ever happened in
the embedding call. So the index can emit exactly the corpus it was built from,
and that emitted tree is by construction the one that reproduces it.

WHAT THIS WRITES

    normalized-canonical/<source>.jsonl    one file per source
    normalized-canonical/MANIFEST.json     counts, checksums, and provenance

The manifest is the point. It records how many records each source should have
and a checksum over their texts, so a rebuild can be verified rather than
assumed, and a future reader knows which tree is authoritative instead of
guessing between three.

This never writes to the index and never deletes an input file.

    export-canonical-corpus --dry-run
    export-canonical-corpus
    export-canonical-corpus --verify     # re-check the tree against the index
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")
FTS_DB = os.path.join(CORPUS, "index", "corpus.db")
OUT_DIR = os.path.join(CORPUS, "normalized-canonical")
FIELDS = ("source", "chat", "date", "who", "sender", "text")


def read_index(vec_db=VEC_DB, fts_db=FTS_DB):
    """Every record, from the vector index, plus the FTS-only ones.

    A record under the 12 character embedding floor is in FTS and not in
    vectors, so exporting from vec_meta alone would quietly drop the short
    turns that make a conversation readable.
    """
    # Duplicates WITHIN the index are kept. The export has to reproduce the
    # index, not improve it: the first version deduplicated on
    # (source, date, text) and silently dropped 8 genuinely repeated gcal
    # records, so a rebuild came out 8 short and the difference looked like a
    # bug rather than a choice. Deduplication is only applied across the
    # vec/FTS merge, where the same record legitimately appears in both.
    rows = defaultdict(list)
    seen = set()
    vec = sqlite3.connect(f"file:{vec_db}?mode=ro", uri=True)
    try:
        for r in vec.execute("SELECT source, chat, date, who, sender, text FROM vec_meta "
                             "ORDER BY rowid"):
            rec = dict(zip(FIELDS, [x if x is not None else "" for x in r]))
            seen.add((rec["source"], rec["date"], rec["text"]))
            rows[rec["source"]].append(rec)
    finally:
        vec.close()

    short = 0
    if os.path.exists(fts_db):
        fts = sqlite3.connect(f"file:{fts_db}?mode=ro", uri=True)
        try:
            for r in fts.execute("SELECT source, chat, date, who, sender, text FROM msgs"):
                rec = dict(zip(FIELDS, [x if x is not None else "" for x in r]))
                key = (rec["source"], rec["date"], rec["text"])
                if key in seen:
                    continue
                seen.add(key)
                rows[rec["source"]].append(rec)
                short += 1
        finally:
            fts.close()
    return rows, short


def checksum(records):
    h = hashlib.sha256()
    for text in sorted(r["text"] for r in records):
        h.update(text.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def load_tree(out_dir=OUT_DIR):
    rows = defaultdict(list)
    for name in sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []:
        if not name.endswith(".jsonl"):
            continue
        for line in open(os.path.join(out_dir, name), encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rows[r.get("source", "")].append(r)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="compare the existing tree against the index and report drift")
    args = ap.parse_args()

    rows, short = read_index()
    total = sum(len(v) for v in rows.values())

    if args.verify:
        tree = load_tree(args.out)
        if not tree:
            print(f"no canonical tree at {args.out}")
            return 1
        print("%-12s %8s %8s %s" % ("source", "index", "files", "checksum"))
        drift = 0
        for src in sorted(set(rows) | set(tree)):
            a, b = rows.get(src, []), tree.get(src, [])
            ca, cb = checksum(a), checksum(b)
            ok = ca == cb
            drift += 0 if ok else 1
            print("%-12s %8d %8d %s" % (src, len(a), len(b), "match" if ok else f"DRIFT {ca} vs {cb}"))
        print(f"\n{'in sync' if not drift else str(drift) + ' source(s) drifted'}")
        return 0

    print(f"{total} records across {len(rows)} sources")
    if short:
        print(f"  {short} of them are below the embedding floor and exist only in FTS")
    for src in sorted(rows):
        print("  %-12s %6d" % (src, len(rows[src])))

    if args.dry_run:
        print(f"\ndry run. Would write {args.out}")
        return 0

    os.makedirs(args.out, exist_ok=True)
    manifest = {"written": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_of_truth": "index/vectors.db + index/corpus.db",
                "record_shape": list(FIELDS), "sources": {}}
    for src, recs in sorted(rows.items()):
        path = os.path.join(args.out, f"{src or 'unknown'}.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        manifest["sources"][src] = {"records": len(recs), "checksum": checksum(recs),
                                    "file": os.path.basename(path)}
    manifest["total_records"] = total
    with open(os.path.join(args.out, "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"\nwrote {args.out}")
    print("  MANIFEST.json records the per-source count and checksum, so a rebuild "
          "can be verified rather than assumed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
