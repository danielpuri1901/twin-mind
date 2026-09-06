#!/bin/sh
# The ship gate: NO skill/prompt/model change ships without this passing.
# Usage: evals/eval.sh          (triage regression suite - fast, ~2 cents)
#        evals/eval.sh --full   (also gold-32 drafting benchmark - slower, ~40 cents)
set -e
cd "$(dirname "$0")/.."
PY="$HOME/.hermes/hermes-agent/venv/bin/python"
echo "== tool regression tests (deterministic, free) =="
python3 evals/test_tools.py
echo "== project activity collector (deterministic, free) =="
python3 evals/test_project_activity_collector.py
echo "== project activity ranking and novelty (deterministic, free) =="
python3 evals/test_project_activity.py
echo "== project-bound brief composition (deterministic, free) =="
python3 evals/test_compose_brief.py
echo "== background-prep calendar physics (deterministic, free) =="
python3 evals/test_prep_scan.py
echo "== brief watchdog matches the brief format (anti-drift, free) =="
python3 evals/test_brief_check.py
echo "== granola transcript ingest (deterministic, free) =="
python3 evals/test_granola_fetch.py
echo "== regression suite: past mistakes stay fixed (bar: 100%) =="
"$PY" evals/run_regression.py --trials 3
if [ "$1" = "--full" ]; then
  echo "== brief composition benchmark (the REAL job; latest fixture) =="
  "$PY" evals/run_brief_bench.py
fi
if [ "$1" = "--judges" ] || [ "$1" = "--full" ]; then
  # Judge-regression gate: run each calibrated judge over its golden set and block if it drops
  # below its floor. LIVE - makes Bedrock + LangSmith calls (~2 cents), so it is gated behind a
  # flag, not on the free/deterministic default path. Run it on any judge or prompt change.
  echo "== judge-alignment gate: insight (live: Bedrock + LangSmith) =="
  "$PY" evals/align.py insight --gate
  # coach joins once coach-faithfulness-golden is labeled:
  # "$PY" evals/align.py coach --gate
fi
echo "EVAL GATE: GREEN"
