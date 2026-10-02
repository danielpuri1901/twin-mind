"""Answer one question: is corpus-rag actually firing, and on what?

Open since 2026-09-24 and unanswerable until now, because the plugin logged at
INFO and the gateway journals WARNING and above, so the evidence never
existed. The plugin now writes its own counter file and this reads it.

What the outcomes mean:

  injected    the corpus was searched and hits went into the turn. This is the
              plugin doing its job.
  empty       the corpus was searched and returned nothing. Not a skip: the
              lookup happened. A high rate here is a retrieval problem, not a
              plugin problem, and it is the number that argues for an eval set.
  skipped     a greeting or an ack, deliberately not searched.
  error       the hook raised and failed open, so the turn survived without
              context. Any of these is worth reading.
  registered  the plugin loaded. Its absence means the plugin is not installed,
              which is a different diagnosis from "it never fires".

    rag-stats [--days 7] [--json]
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
STATS = os.environ.get("CORPUS_RAG_STATS") or os.path.join(CORPUS, "rag-stats.jsonl")


def read(path, since=None):
    rows = []
    try:
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if since:
                try:
                    if datetime.fromisoformat(row["at"]) < since:
                        continue
                except (KeyError, ValueError):
                    pass
            rows.append(row)
    except FileNotFoundError:
        return None
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=STATS)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    rows = read(args.file, since)

    if rows is None:
        print(f"no counter file at {args.file}")
        print("The plugin has not run since the counter was added, or the gateway "
              "has not been restarted to pick it up.")
        return 1
    if not rows:
        print(f"counter file exists but holds nothing in the last {args.days} days")
        return 0

    outcomes = Counter(r.get("outcome", "?") for r in rows)
    turns = sum(v for k, v in outcomes.items() if k != "registered")
    searched = outcomes["injected"] + outcomes["empty"]

    if args.json:
        print(json.dumps({"file": args.file, "days": args.days, "turns": turns,
                          "outcomes": dict(outcomes)}, indent=2))
        return 0

    print(f"{args.file}\nlast {args.days} days: {turns} turns\n")
    for outcome in ("injected", "empty", "skipped", "error", "registered"):
        n = outcomes.get(outcome, 0)
        if not n and outcome == "registered":
            continue
        share = f"{100 * n / turns:5.1f}%" if turns and outcome != "registered" else "     "
        print(f"  {outcome:<11} {n:5d} {share}")

    if searched:
        hits = [r["hits"] for r in rows if r.get("outcome") == "injected" and "hits" in r]
        by_source = Counter()
        for r in rows:
            for s in r.get("sources", []):
                by_source[s] += 1
        print(f"\nsearched on {searched} of {turns} turns "
              f"({100 * searched / turns:.0f}%)")
        if hits:
            print(f"hits when injected: min {min(hits)}, max {max(hits)}, "
                  f"mean {sum(hits) / len(hits):.1f}")
        if by_source:
            print("\nsources that reached the model:")
            for src, n in by_source.most_common():
                print(f"  {src:<12} {n:5d}")

    if outcomes["error"]:
        print(f"\n{outcomes['error']} turns failed open. Reasons:")
        for reason, n in Counter(r.get("reason", "?") for r in rows
                                 if r.get("outcome") == "error").most_common():
            print(f"  {reason}: {n}")

    if outcomes["empty"] and searched:
        share = 100 * outcomes["empty"] / searched
        if share > 25:
            print(f"\n{share:.0f}% of searches returned nothing. That is a retrieval "
                  "problem rather than a plugin problem, and it is the case for "
                  "building the eval set before tuning anything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
