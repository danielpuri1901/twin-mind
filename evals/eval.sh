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
echo "== wispr flow meeting ingest (deterministic, free) =="
python3 evals/test_wispr_ingest.py
echo "== weekly recap reads meetings from the corpus (deterministic, free) =="
python3 evals/test_recap_meetings.py
echo "== corpus sync never uploads a failed snapshot (deterministic, free) =="
python3 evals/test_corpus_sync.py
echo "== dossier queries stay clean and failures stay loud (deterministic, free) =="
python3 evals/test_compose_prep.py
echo "== auto-retrieval crashes are never read as empty (deterministic, free) =="
python3 evals/test_corpus_rag_stats.py
echo "== chat-alive rule and chat Langfuse traces (deterministic, free) =="
python3 evals/test_chat_observability.py
echo "== recap headlines accept both CHANGELOG heading forms (deterministic, free) =="
python3 evals/test_recap_headlines.py
echo "== regression suite: past mistakes stay fixed (bar: 100%) =="
"$PY" evals/run_regression.py --trials 3
if [ "$1" = "--full" ]; then
  echo "== brief composition benchmark (the REAL job; latest fixture) =="
  "$PY" evals/run_brief_bench.py
fi
if [ "$1" = "--judges" ] || [ "$1" = "--full" ]; then
  # Judge-regression gate: run each calibrated judge over its golden set and block if it drops
  # below its floor. LIVE - makes Anthropic API + Langfuse calls (~2 cents), so it is gated behind a
  # flag, not on the free/deterministic default path. Run it on any judge or prompt change.
  echo "== judge-alignment gate: insight (live: Anthropic API + Langfuse) =="
  "$PY" evals/align.py insight --gate
  # coach joins once coach-faithfulness-golden is labeled:
  # "$PY" evals/align.py coach --gate
fi
echo "EVAL GATE: GREEN"
