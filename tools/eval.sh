#!/bin/sh
# The ship gate: NO skill/prompt/model change ships without this passing.
# Usage: tools/eval.sh          (triage regression suite - fast, ~2 cents)
#        tools/eval.sh --full   (also gold-32 drafting benchmark - slower, ~40 cents)
set -e
cd "$(dirname "$0")/.."
PY="$HOME/.hermes/hermes-agent/venv/bin/python"
echo "== regression suite: past mistakes stay fixed (bar: 100%) =="
"$PY" tools/run_regression.py --trials 3
if [ "$1" = "--full" ]; then
  echo "== drafting benchmark: how good is it getting (no bar; compare runs) =="
  "$PY" tools/run_benchmark.py
fi
echo "EVAL GATE: GREEN"
