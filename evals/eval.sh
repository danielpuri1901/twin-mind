#!/bin/sh
# The ship gate: NO skill/prompt/model change ships without this passing.
# Usage: evals/eval.sh          (triage regression suite - fast, ~2 cents)
#        evals/eval.sh --full   (also gold-32 drafting benchmark - slower, ~40 cents)
set -e
cd "$(dirname "$0")/.."
PY="$HOME/.hermes/hermes-agent/venv/bin/python"
echo "== tool regression tests (deterministic, free) =="
python3 evals/test_tools.py
echo "== regression suite: past mistakes stay fixed (bar: 100%) =="
"$PY" evals/run_regression.py --trials 3
if [ "$1" = "--full" ]; then
  echo "== brief composition benchmark (the REAL job; latest fixture) =="
  "$PY" evals/run_brief_bench.py
fi
echo "EVAL GATE: GREEN"
