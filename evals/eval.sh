#!/bin/sh
# The ship gate: NO skill/prompt/model change ships without this passing.
# Usage: evals/eval.sh    (free tests, then the triage regression suite, ~2 cents)
set -e
cd "$(dirname "$0")/.."
PY="$HOME/.twin-mind/venv/bin/python"
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
echo "== corpus parity check catches keyword rows with no vectors (deterministic, free) =="
python3 evals/test_corpus_parity.py
echo "== every corpus writer uses one embedding contract (deterministic, free) =="
python3 evals/test_embedding_contract.py
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
echo "EVAL GATE: GREEN"
