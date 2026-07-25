#!/usr/bin/env python3
"""Promotion gate: does the windowed+contextual win survive under HYBRID (production's real mode)?

The retrieval eval measured the semantic lane only. Production serves hybrid (FTS + vector + RRF),
so before we swap the production indexes we check source_recall@10 under hybrid for:
  - prod        = per-turn vectors.db + per-turn corpus.db (what production runs today)
  - candidate   = windowed+contextual vectors + windowed+contextual FTS (the promotion)
on the 30 home-labeled questions. Promote only if candidate >= prod.

Reuses the production fusion (shared/corpus_search.rrf_fuse) so this measures the real retriever.
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, "/home/ec2-user/super-project/evals")
sys.path.insert(0, "/home/ec2-user/super-project/shared")
import retrieval_eval as RE
import corpus_search as CS   # fts_query, rrf_fuse (the production fusion)

IDX = os.path.join(RE.ROOT, "index")


def fts_rows(fts_db, query, k):
    db = sqlite3.connect(fts_db)
    q = CS.fts_query(query)
    if not q:
        return []
    return db.execute(
        "SELECT source, chat, date, who, sender, text, bm25(msgs) AS score "
        "FROM msgs WHERE msgs MATCH ? ORDER BY score LIMIT ?", (q, k)).fetchall()


def vec_rows(vec_db, query, k):
    db = RE.connect(vec_db)
    top = RE.retrieve(db, RE.embed_query(query), k)
    db.close()
    return [(c["source"], c["chat"], c["date"], c["who"], c["sender"], c["text"], c["distance"]) for c in top]


def hybrid(vec_db, fts_db, query, k):
    sem = vec_rows(vec_db, query, k)
    lex = fts_rows(fts_db, query, k)
    return CS.rrf_fuse(lex, sem, k)   # rows: (source, chat, date, who, sender, text, -score)


def main():
    rows = [json.loads(l) for l in open(RE.QA, encoding="utf-8")]
    home = [r for r in rows if r.get("home")]
    print(f"home-labeled rows: {len(home)}")
    arms = [
        ("prod (per-turn hybrid)", os.path.join(IDX, "vectors.db"), os.path.join(IDX, "corpus.db")),
        ("candidate (windowed+ctx hybrid)", os.path.join(IDX, "vectors-windowed-ctx.db"),
         os.path.join(IDX, "corpus-windowed-ctx.db")),
    ]
    for label, vec_db, fts_db in arms:
        if not (os.path.exists(vec_db) and os.path.exists(fts_db)):
            print(f"{label}: MISSING index(es), skip"); continue
        H = {3: 0, 5: 0, 10: 0}
        for r in home:
            fused = hybrid(vec_db, fts_db, r["question"], 20)
            for k in (3, 5, 10):
                if any(row[1] == r["home"]["chat"] for row in fused[:k]):
                    H[k] += 1
        print(f"{label:34} " + "  ".join(f"@{k}={H[k]/len(home):.3f}" for k in (3, 5, 10)))


if __name__ == "__main__":
    main()
