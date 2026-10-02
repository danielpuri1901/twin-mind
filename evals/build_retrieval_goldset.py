"""Build a retrieval gold set from real traces, with no human labelling.

The inputs were never the hard part: every question Daniel has asked is
already in the corpus as a `twin-chat` record with who='me'. The hard part is
ground truth, which normally means someone sitting down and saying what the
right answer was.

It does not have to, because the twin's reply is the very next record. So:

    question  = a twin-chat turn from Daniel
    answer    = the twin-chat turn from the twin immediately after it
    gold docs = the NON twin-chat records that contain the distinctive parts
                of that answer

If the twin said something specific and that specific thing also appears in a
meeting, an email or a transcript, then that record is where the answer lived,
whether or not retrieval actually surfaced it at the time. If the answer's
distinctive content appears nowhere in the corpus, the twin answered from
general knowledge and the case is dropped. That filter is the reason this
works: it keeps exactly the questions the corpus was supposed to answer.

"Distinctive" is deliberately mechanical. A token counts when it is at least
four characters, is not a stopword, and appears in fewer than 2% of records.
Rare tokens are what make a match evidence rather than coincidence; "the
project" matches everything and means nothing. A record needs two of them to
be called gold, so a single shared surname is not sufficient.

No model is involved in building the set, so nothing here can hallucinate a
label. What it cannot do is judge whether an answer was *good*; it only knows
where the material for it lived. That is the right scope, because the thing
being measured is retrieval.

    build-retrieval-goldset --out ~/twin-corpus/datasets/corpus-qa.jsonl
    build-retrieval-goldset --measure    # also score current retrieval on it
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
DB = os.path.join(CORPUS, "index", "corpus.db")
SEARCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared",
                      "corpus_search.py")

QUESTION = re.compile(
    r"^(what|when|where|who|which|why|how|did|do|does|can|could|is|are|was|were|"
    r"should|have|has|tell me|find|show me|remind|list|summar)\b", re.I)

STOP = set((
    "the a an and or but if then than that this these those there here when where "
    "what which who whom whose why how all any both each few more most other some "
    "such only own same so too very can will just should now also about into over "
    "with from your you yours have has had been being was were are is am be do does "
    "did done get got make made like want need know think said say says thing things "
    "really actually maybe okay yeah yes not no for it its they them their we our us "
    "i me my mine he she his her him hers on in at to of as by be").split())

# Trailing punctuation must not survive tokenisation. The first version's
# pattern allowed it, so "guard." and "phone." became distinct rare tokens,
# and a rare token that is really a common word with a full stop attached
# matches records by accident. That alone produced gold documents like a bank
# statement for a question about verbatim text.
TOKEN = re.compile(r"[a-z][a-z0-9'\-]{3,}")


def tokens(text):
    return [t.strip("'-") for t in TOKEN.findall((text or "").lower())
            if t.strip("'-") not in STOP and len(t.strip("'-")) >= 4]


def load_pairs(db):
    """(question, answer) from consecutive twin-chat turns."""
    rows = db.execute(
        "select date, who, text from msgs where source='twin-chat' "
        "order by date, rowid").fetchall()
    pairs = []
    for i in range(len(rows) - 1):
        d, who, text = rows[i]
        nd, nwho, ntext = rows[i + 1]
        if who != "me" or nwho != "twin":
            continue
        q, a = (text or "").strip(), (ntext or "").strip()
        if not (15 <= len(q) <= 300) or len(a) < 60:
            continue
        if not (q.endswith("?") or QUESTION.match(q)):
            continue
        pairs.append({"date": d, "question": q, "answer": a})
    return pairs


def document_frequency(db):
    """How many records contain each token. Computed once over the corpus."""
    df = Counter()
    total = 0
    for (text,) in db.execute("select text from msgs"):
        total += 1
        for t in set(tokens(text)):
            df[t] += 1
    return df, total


def distinctive(answer, question, df, total, max_docs=20, limit=12):
    """Rare tokens the ANSWER introduces, rarest first.

    Tokens already present in the question are excluded. Matching on those
    would only prove the question's own words appear somewhere, which is
    circular: the gold document has to be evidence for the ANSWER.

    max_docs is an absolute count, not a share. At 8,324 records a 2% share
    allowed a token in 166 of them to count as rare, which is how conversational
    filler qualified.
    """
    asked = set(tokens(question))
    seen = set(tokens(answer)) - asked
    scored = [(df.get(t, 0), t) for t in seen if 0 < df.get(t, 0) <= max_docs]
    scored.sort()
    return [t for _n, t in scored[:limit]]


def gold_records(db, terms, min_hits=4, limit=5):
    """Non twin-chat records containing at least min_hits of the rare terms."""
    # Four independent rare terms in one record. Two was coincidence.
    if len(terms) < min_hits:
        return []
    quoted = " OR ".join('"%s"' % t.replace('"', "") for t in terms)
    try:
        rows = db.execute(
            "select source, chat, date, text from msgs where msgs match ? "
            "and source != 'twin-chat' limit 400", (quoted,)).fetchall()
    except sqlite3.OperationalError:
        return []
    scored = []
    for source, chat, date, text in rows:
        have = set(tokens(text))
        hits = sum(1 for t in terms if t in have)
        if hits >= min_hits:
            scored.append((hits, {"source": source, "chat": chat, "date": date,
                                  "text": text}))
    scored.sort(key=lambda x: -x[0])
    return [r for _h, r in scored[:limit]]


def retrieve(question, k=5):
    proc = subprocess.run([sys.executable, SEARCH, question, "--k", str(k)],
                          capture_output=True, text=True, timeout=60)
    return [json.loads(ln) for ln in proc.stdout.splitlines()
            if ln.strip().startswith("{")]


def measure(cases, k=5):
    """recall@k and MRR against the derived gold documents."""
    hit, rr, scored = 0, 0.0, 0
    for c in cases:
        gold = {g["text"] for g in c["gold"]}
        try:
            got = retrieve(c["question"], k)
        except Exception as exc:
            print(f"  retrieval failed: {exc}", file=sys.stderr)
            continue
        scored += 1
        rank = next((i for i, r in enumerate(got) if r.get("text") in gold), None)
        c["hit"] = rank is not None
        c["rank"] = None if rank is None else rank + 1
        if rank is not None:
            hit += 1
            rr += 1.0 / (rank + 1)
    return {"cases": scored, "recall_at_k": hit / scored if scored else 0.0,
            "mrr": rr / scored if scored else 0.0, "k": k}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--out", default=os.path.join(CORPUS, "datasets", "corpus-qa.jsonl"))
    ap.add_argument("--measure", action="store_true", help="also score current retrieval")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min-hits", type=int, default=4,
                    help="rare terms a record must share with the answer to count as gold")
    ap.add_argument("--max-docs", type=int, default=20,
                    help="a term in more records than this is not rare")
    args = ap.parse_args()

    db = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)
    pairs = load_pairs(db)
    # The same question asked twice is one eval case, not two.
    seen_q, deduped = set(), []
    for p in pairs:
        key = re.sub(r"\W+", " ", p["question"].lower()).strip()
        if key in seen_q:
            continue
        seen_q.add(key)
        deduped.append(p)
    print(f"question/answer pairs in traces: {len(pairs)} ({len(deduped)} unique)")
    pairs = deduped

    df, total = document_frequency(db)
    print(f"vocabulary: {len(df)} tokens over {total} records")

    cases, dropped = [], 0
    for p in pairs:
        terms = distinctive(p["answer"], p["question"], df, total, args.max_docs)
        gold = gold_records(db, terms, args.min_hits)
        if not gold:
            dropped += 1
            continue
        cases.append({"date": p["date"][:10], "question": p["question"],
                      "answer": p["answer"][:400], "terms": terms, "gold": gold})
    print(f"cases with gold documents: {len(cases)}  (dropped {dropped}: the twin "
          f"answered from general knowledge, so the corpus was not the source)")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}")

    if args.measure and cases:
        print(f"\nmeasuring current retrieval at k={args.k} ...")
        m = measure(cases, args.k)
        print(f"\n  cases      {m['cases']}")
        print(f"  recall@{m['k']}   {m['recall_at_k']:.2f}")
        print(f"  MRR        {m['mrr']:.3f}")
        misses = [c for c in cases if c.get("hit") is False]
        if misses:
            print(f"\n  {len(misses)} misses. The corpus holds the answer and "
                  f"retrieval did not return it:")
            for c in misses[:12]:
                print(f"    {c['date']}  {c['question'][:84]}")
        with open(args.out.replace(".jsonl", "-scored.jsonl"), "w", encoding="utf-8") as fh:
            for c in cases:
                fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
