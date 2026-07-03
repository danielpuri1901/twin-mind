#!/usr/bin/env python3
"""
corpus_search.py - THE retrieval contract for the twin.

    corpus-search "query" [--k 20] [--since YYYY-MM-DD] [--who me|them]

Prints JSON lines: {source, chat, date, who, sender, text, score}.
Everything (Hermes skills, eval judges, future agents) calls ONLY this
contract. The backend (SQLite FTS5 today, embeddings someday) is swappable
behind it without touching any consumer.
"""
import argparse
import json
import os
import sqlite3

ROOT = os.environ.get("TWIN_CORPUS", os.path.expanduser("~/twin-corpus"))
DB = os.path.join(ROOT, "index", "corpus.db")
VECDB = os.path.join(ROOT, "index", "vectors.db")


def fts_query(raw):
    # Quote each token so user text with FTS5 operators can't break the query.
    return " ".join('"' + t.replace('"', "") + '"' for t in raw.split() if t.strip('"'))


def semantic_rows(query, k, since=None, until=None, who=None, chat=None):
    """Vector lane: Cohere query embedding -> sqlite-vec KNN, filters applied post-KNN."""
    import boto3
    import json as _json
    import sqlite_vec
    brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
    r = brt.invoke_model(modelId="cohere.embed-multilingual-v3",
                         body=_json.dumps({"texts": [query[:1500]],
                                           "input_type": "search_query"}))
    qv = _json.loads(r["body"].read())["embeddings"][0]
    db = sqlite3.connect(VECDB)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    rows = db.execute(
        "SELECT m.source, m.chat, m.date, m.who, m.sender, m.text, v.distance "
        "FROM vec_idx v JOIN vec_meta m ON m.rowid = v.rowid "
        "WHERE v.embedding MATCH ? AND k = ?",
        (sqlite_vec.serialize_float32(qv), k * 5)).fetchall()
    out = []
    for row in rows:
        if since and row[2] < since:
            continue
        if until and row[2] > until:
            continue
        if who and row[3] != who:
            continue
        if chat and chat.lower() not in (row[1] or "").lower():
            continue
        out.append(row)
        if len(out) >= k:
            break
    return out


def rrf_fuse(lex, sem, k, c=60):
    """Reciprocal-rank fusion of the two lanes; text as identity."""
    score = {}
    for rank, row in enumerate(lex):
        score.setdefault(row[5], [row, 0.0])
        score[row[5]][1] += 1.0 / (c + rank + 1)
    for rank, row in enumerate(sem):
        score.setdefault(row[5], [row, 0.0])
        score[row[5]][1] += 1.0 / (c + rank + 1)
    fused = sorted(score.values(), key=lambda x: x[1], reverse=True)[:k]
    return [tuple(list(row[:6]) + [-s]) for row, s in fused]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--since", default=None)
    ap.add_argument("--who", choices=["me", "them"], default=None)
    ap.add_argument("--chat", default=None,
                    help="filter to one conversation/correspondent (substring match)")
    ap.add_argument("--until", default=None, help="only records dated on/before this")
    ap.add_argument("--any", action="store_true",
                    help="OR semantics: match any token instead of all")
    ap.add_argument("--mode", choices=["lexical", "semantic", "hybrid"],
                    default="hybrid", help="retrieval backend (contract stays identical); "
                    "hybrid is the eval-chosen default (bake-off 2026-07-03)")
    args = ap.parse_args()

    cols = ["source", "chat", "date", "who", "sender", "text", "score"]

    if args.mode in ("semantic", "hybrid"):
        sem = semantic_rows(args.query, args.k, args.since, args.until,
                            args.who, args.chat)
        if args.mode == "semantic":
            for row in sem:
                print(json.dumps(dict(zip(cols, row)), ensure_ascii=False))
            return

    q = fts_query(args.query)
    if args.any:
        q = " OR ".join(q.split())
    sql = ("SELECT source, chat, date, who, sender, text, bm25(msgs) AS score "
           "FROM msgs WHERE msgs MATCH ?")
    params = [q]
    if args.since:
        sql += " AND date >= ?"
        params.append(args.since)
    if args.until:
        sql += " AND date <= ?"
        params.append(args.until)
    if args.who:
        sql += " AND who = ?"
        params.append(args.who)
    if args.chat:
        sql += " AND chat LIKE ?"
        params.append(f"%{args.chat}%")
    sql += " ORDER BY score LIMIT ?"
    params.append(args.k)

    db = sqlite3.connect(DB)
    lex = db.execute(sql, params).fetchall()

    if args.mode == "hybrid":
        rows = rrf_fuse(lex, sem, args.k)
    else:
        rows = lex
    for row in rows:
        print(json.dumps(dict(zip(cols, row)), ensure_ascii=False))


if __name__ == "__main__":
    main()
