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


def fts_query(raw, require_all=False):
    """Tokens quoted, then joined with OR unless every one is required.

    The join matters more than it looks. FTS5 treats space-separated terms as
    an implicit AND, and this function used to join with a space, so the
    lexical lane demanded that EVERY word of the query appear in one record.
    For a natural-language question that is almost never true.

    Measured on LongMemEval_S, 470 labelled questions with 115k-token
    histories, 2026-09-28:

        implicit AND   recall@10 = 0.00
        explicit OR    recall@10 = 0.84

    It also explains a symptom that looked unrelated. The one record certain
    to contain every word of a question is the question itself, so the only
    thing the AND form could match was Daniel's own past phrasing of the same
    question. The corpus appeared to retrieve his questions back at him
    because that was the only match the query permitted.

    BM25 still ranks, so OR does not mean loose: a record matching six rare
    terms outranks one matching a single common term.
    """
    terms = ['"' + t.replace('"', "") + '"' for t in raw.split() if t.strip('"')]
    if not terms:
        return ""
    return " ".join(terms) if require_all else " OR ".join(terms)


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
    ap.add_argument("--as-of", dest="as_of", default=None,
                    help="resolve relative dates against this date (YYYY-MM-DD) instead of "
                         "today. Needed to replay a benchmark or a historical question, where "
                         "'one year ago' means one year before the question was asked.")
    ap.add_argument("--time-expand", dest="time_expand", action="store_true",
                    help="resolve a relative date in the query into --since/--until. "
                         "A regex gates the model call, so questions with no temporal "
                         "cue cost nothing. Explicit --since/--until always win.")
    ap.add_argument("--all", dest="require_all", action="store_true",
                    help="require EVERY token to appear in the record. Rarely what you "
                         "want: it scored 0.00 recall@10 on LongMemEval_S, because a "
                         "natural-language question has no record containing all its words")
    ap.add_argument("--any", action="store_true",
                    help="deprecated and now the default; accepted so old callers keep working")
    ap.add_argument("--mode", choices=["lexical", "semantic", "hybrid"],
                    default="hybrid", help="retrieval backend (contract stays identical); "
                    "hybrid is the eval-chosen default (bake-off 2026-07-03)")
    args = ap.parse_args()

    # Time expansion runs before either lane, because both of them filter on the
    # same dates. Explicit flags win: a caller that named a range meant it.
    if args.time_expand and not (args.since or args.until):
        try:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from datetime import datetime as _dt
            from shared.query_time import extract_range
            ref = _dt.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else None
            args.since, args.until = extract_range(args.query, ref)
        except Exception:
            pass  # fail open: no filter beats no answer

    cols = ["source", "chat", "date", "who", "sender", "text", "score"]

    if args.mode in ("semantic", "hybrid"):
        sem = semantic_rows(args.query, args.k, args.since, args.until,
                            args.who, args.chat)
        if args.mode == "semantic":
            for row in sem:
                print(json.dumps(dict(zip(cols, row)), ensure_ascii=False))
            return

    q = fts_query(args.query, require_all=args.require_all)
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
