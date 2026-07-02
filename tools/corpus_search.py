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


def fts_query(raw):
    # Quote each token so user text with FTS5 operators can't break the query.
    return " ".join('"' + t.replace('"', "") + '"' for t in raw.split() if t.strip('"'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--since", default=None)
    ap.add_argument("--who", choices=["me", "them"], default=None)
    ap.add_argument("--chat", default=None,
                    help="filter to one conversation/correspondent (substring match)")
    args = ap.parse_args()

    sql = ("SELECT source, chat, date, who, sender, text, bm25(msgs) AS score "
           "FROM msgs WHERE msgs MATCH ?")
    params = [fts_query(args.query)]
    if args.since:
        sql += " AND date >= ?"
        params.append(args.since)
    if args.who:
        sql += " AND who = ?"
        params.append(args.who)
    if args.chat:
        sql += " AND chat LIKE ?"
        params.append(f"%{args.chat}%")
    sql += " ORDER BY score LIMIT ?"
    params.append(args.k)

    db = sqlite3.connect(DB)
    cols = ["source", "chat", "date", "who", "sender", "text", "score"]
    for row in db.execute(sql, params):
        print(json.dumps(dict(zip(cols, row)), ensure_ascii=False))


if __name__ == "__main__":
    main()
