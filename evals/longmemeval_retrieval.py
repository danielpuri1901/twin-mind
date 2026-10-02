"""Run LongMemEval against the twin's OWN retrieval stack.

Not the paper's retrievers. The point is not to reproduce their numbers, it is
to find out what `shared/corpus_search.py` scores on 500 questions that
someone else labelled, because every attempt to build a gold set from Daniel's
own 55 traces failed for lack of ground truth.

Why this needs no model calls and no OpenAI key: LongMemEval marks the turns
that contain the evidence with `has_answer: true`. Retrieval recall is then a
set membership test, not a judgement. The paper's QA score needs GPT-4o as a
judge; retrieval recall does not, and retrieval is the part being changed.

Each question gets its own scratch corpus, because the benchmark's premise is
that the question must be answered from that question's history and nothing
else. The records are built in the twin's own shape
({source, chat, date, who, sender, text}) at TURN granularity, which is how
the real corpus stores messages, so the measurement transfers.

    longmemeval-retrieval --data longmemeval_oracle.json --mode lexical
    longmemeval-retrieval --data longmemeval_s_cleaned.json --mode hybrid --limit 50

`--mode lexical` costs nothing and needs no network. `semantic` and `hybrid`
embed every turn of every haystack, so they are metered: use --limit.
"""

import argparse
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH = os.path.join(HERE, "..", "shared", "corpus_search.py")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The benchmark index must be built exactly as production builds one, or the
# number measures the harness instead of the system.
from shared.embedding import (BATCH_INCREMENTAL, MAX_CHARS, MIN_CHARS, MODEL as EMBED_MODEL,
                              embed_body, worth_embedding)


def _as_of(raw):
    """LongMemEval dates look like '2023/04/10 (Mon) 23:07'. Take the day."""
    raw = (raw or "").strip()
    if len(raw) >= 10 and raw[4] == "/" and raw[7] == "/":
        return raw[:10].replace("/", "-")
    return None


def records_for(instance):
    """Turn-level records in the twin's own shape, plus the evidence set.

    `has_answer` lives on a turn, so the gold is a set of turn texts. Text is
    the identity because that is what corpus_search returns and what rrf_fuse
    already uses to fuse its two lanes.
    """
    rows, gold = [], set()
    sessions = instance.get("haystack_sessions") or []
    dates = instance.get("haystack_dates") or []
    ids = instance.get("haystack_session_ids") or []
    for i, session in enumerate(sessions):
        date = dates[i] if i < len(dates) else ""
        sid = ids[i] if i < len(ids) else f"session-{i}"
        for turn in session or []:
            text = (turn.get("content") or "").strip()
            if not text:
                continue
            role = turn.get("role", "")
            rows.append({
                "source": "longmemeval",
                "chat": str(sid),
                "date": str(date),
                "who": "me" if role == "user" else "twin",
                "sender": "Daniel" if role == "user" else "Twin Mind",
                "text": text,
            })
            if turn.get("has_answer"):
                gold.add(text)
    return rows, gold


def build_fts(rows, path):
    db = sqlite3.connect(path)
    db.execute("CREATE VIRTUAL TABLE msgs USING fts5(source, chat, date, who, sender, text)")
    db.executemany("INSERT INTO msgs VALUES (?,?,?,?,?,?)",
                   [(r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"])
                    for r in rows])
    db.commit()
    db.close()


def build_vectors(rows, path, client):
    import sqlite_vec
    worth = [r for r in rows if worth_embedding(r["text"])]
    if not worth:
        return 0
    vecs = []
    for i in range(0, len(worth), BATCH_INCREMENTAL):
        body = embed_body([r["text"] for r in worth[i:i + BATCH_INCREMENTAL]])
        payload = client.invoke_model(modelId=EMBED_MODEL, body=body)["body"].read()
        vecs += json.loads(payload)["embeddings"]
    db = sqlite3.connect(path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.execute("CREATE TABLE vec_meta(rowid INTEGER PRIMARY KEY, source TEXT, chat TEXT, "
               "date TEXT, who TEXT, sender TEXT, text TEXT, model TEXT, "
               "embed_chars INTEGER)")
    db.execute("CREATE VIRTUAL TABLE vec_idx USING vec0(embedding float[1024])")
    for n, (r, v) in enumerate(zip(worth, vecs), 1):
        db.execute("INSERT INTO vec_meta (rowid, source, chat, date, who, sender, text, model, "
                   "embed_chars) VALUES (?,?,?,?,?,?,?,?,?)",
                   (n, r["source"], r["chat"], r["date"], r["who"], r["sender"],
                    r["text"], EMBED_MODEL, MAX_CHARS))
        db.execute("INSERT INTO vec_idx(rowid, embedding) VALUES (?,?)",
                   (n, sqlite_vec.serialize_float32(v)))
    db.commit()
    db.close()
    return len(vecs)


def search(root, question, k, mode, any_tokens=False, time_expand=False, as_of=None):
    """One call into the real contract, with TWIN_CORPUS pointed at the scratch tree.

    `any_tokens` maps to corpus_search's --any. It matters more than it looks:
    fts_query joins quoted terms with a space, which FTS5 reads as an implicit
    AND, so the default requires every word of the question to appear in one
    record. For a natural-language question that is almost never true.
    """
    env = dict(os.environ, TWIN_CORPUS=root)
    cmd = [sys.executable, SEARCH, question, "--k", str(k), "--mode", mode]
    if any_tokens:
        cmd.append("--any")
    if time_expand:
        # The reference date must be the question's own date. LongMemEval
        # questions are dated 2023, so resolving "one year ago" against today
        # would filter to a range the haystack cannot contain, and the feature
        # would measure as catastrophic rather than absent.
        cmd.append("--time-expand")
        if as_of:
            cmd += ["--as-of", as_of]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
    return [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--mode", default="lexical", choices=["lexical", "semantic", "hybrid"])
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0, help="first N questions only")
    ap.add_argument("--per-type", type=int, default=0,
                    help="N questions of EACH type; the honest way to subsample")
    ap.add_argument("--time-expand", dest="time_expand", action="store_true",
                    help="resolve relative dates in the question into a date filter")
    ap.add_argument("--any", dest="any_tokens", action="store_true",
                    help="OR the query tokens instead of the default AND")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    data = json.load(open(args.data))
    if args.per_type:
        # The file is grouped by question type, so a plain head() samples one
        # type and calls it a benchmark. Take N of each instead.
        buckets = defaultdict(list)
        for inst in data:
            buckets[inst.get("question_type", "unknown")].append(inst)
        data = [inst for b in buckets.values() for inst in b[:args.per_type]]
    elif args.limit:
        data = data[:args.limit]
    print(f"{len(data)} questions from {os.path.basename(args.data)}, "
          f"mode={args.mode}, k={args.k}, "
          f"tokens={'OR' if args.any_tokens else 'AND (default)'}\n")

    client = None
    if args.mode in ("semantic", "hybrid"):
        import boto3
        client = boto3.client("bedrock-runtime", region_name="eu-west-1")

    by_type = defaultdict(lambda: {"n": 0, "hit": 0, "ranks": []})
    results, embedded = [], 0

    for i, inst in enumerate(data, 1):
        qtype = inst.get("question_type", "unknown")
        # Abstention questions refer to events that never happened, so there is
        # no evidence to retrieve and recall is undefined. The paper skips them
        # for retrieval scoring too.
        if str(inst.get("question_id", "")).endswith("_abs"):
            continue
        rows, gold = records_for(inst)
        if not gold or not rows:
            continue

        root = tempfile.mkdtemp(prefix="lme-")
        try:
            os.makedirs(os.path.join(root, "index"), exist_ok=True)
            build_fts(rows, os.path.join(root, "index", "corpus.db"))
            if client is not None:
                embedded += build_vectors(rows, os.path.join(root, "index", "vectors.db"),
                                          client)
            hits = search(root, inst["question"], args.k, args.mode,
                          args.any_tokens, args.time_expand,
                          _as_of(inst.get("question_date", "")))
        finally:
            shutil.rmtree(root, ignore_errors=True)

        rank = next((j for j, h in enumerate(hits) if (h.get("text") or "") in gold), None)
        b = by_type[qtype]
        b["n"] += 1
        if rank is not None:
            b["hit"] += 1
            b["ranks"].append(rank + 1)
        results.append({"question_id": inst.get("question_id"), "type": qtype,
                        "question": inst["question"], "question_date": inst.get("question_date"),
                        "turns": len(rows), "gold_turns": len(gold),
                        "rank": None if rank is None else rank + 1})
        if i % 25 == 0:
            done = sum(v["n"] for v in by_type.values())
            got = sum(v["hit"] for v in by_type.values())
            print(f"  {i}/{len(data)}  recall@{args.k} so far {got}/{done} "
                  f"= {got / max(done, 1):.2f}", file=sys.stderr)

    total_n = sum(v["n"] for v in by_type.values())
    total_hit = sum(v["hit"] for v in by_type.values())
    all_ranks = [r for v in by_type.values() for r in v["ranks"]]

    print(f"\n{'question type':<28} {'n':>4} {'recall@' + str(args.k):>10} {'median rank':>12}")
    for qtype, v in sorted(by_type.items(), key=lambda kv: -kv[1]["n"]):
        med = statistics.median(v["ranks"]) if v["ranks"] else float("nan")
        print(f"{qtype:<28} {v['n']:>4} {v['hit'] / max(v['n'], 1):>10.2f} {med:>12.1f}")
    print(f"{'-' * 58}")
    med = statistics.median(all_ranks) if all_ranks else float("nan")
    print(f"{'ALL':<28} {total_n:>4} {total_hit / max(total_n, 1):>10.2f} {med:>12.1f}")
    if embedded:
        print(f"\nembedded {embedded} turns across {total_n} haystacks")

    out = args.out or f"longmemeval-{args.mode}-k{args.k}.jsonl"
    with open(out, "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nper-question results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
