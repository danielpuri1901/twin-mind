#!/bin/sh
# The ship gate: NO skill/prompt/model change ships without this passing.
# Usage on the box: evals/eval.sh    (free tests, then the triage regression suite, ~2 cents)
# infra/deploy_box.sh runs it before every deploy.
set -e
cd "$(dirname "$0")/.."
PY="$HOME/.twin-mind/venv/bin/python"
# Free tests get an empty home and no AWS role, the same as CI, so they cannot touch real keys or state.
EMPTY=$(mktemp -d)
trap 'rm -rf "$EMPTY"' EXIT
mkdir -p "$EMPTY/.twin-mind/state"
touch "$EMPTY/.twin-mind/.env"
free() { env -i PATH="$PATH" HOME="$EMPTY" AWS_EC2_METADATA_DISABLED=true "$PY" "evals/$1.py"; }
echo "== tool regression tests (deterministic, free) =="
free test_tools
echo "== project activity collector (deterministic, free) =="
free test_project_activity_collector
echo "== project activity ranking and novelty (deterministic, free) =="
free test_project_activity
echo "== project-bound brief composition (deterministic, free) =="
free test_compose_brief
echo "== background-prep calendar physics (deterministic, free) =="
free test_prep_scan
echo "== brief watchdog matches the brief format (anti-drift, free) =="
free test_brief_check
echo "== wispr flow meeting ingest (deterministic, free) =="
free test_wispr_ingest
echo "== weekly recap reads meetings from the corpus (deterministic, free) =="
free test_recap_meetings
echo "== corpus sync never uploads a failed snapshot (deterministic, free) =="
free test_corpus_sync
echo "== corpus parity check catches keyword rows with no vectors (deterministic, free) =="
free test_corpus_parity
echo "== every corpus writer uses one embedding contract (deterministic, free) =="
free test_embedding_contract
echo "== dossier queries stay clean and failures stay loud (deterministic, free) =="
free test_compose_prep
echo "== auto-retrieval crashes are never read as empty (deterministic, free) =="
free test_corpus_rag_stats
echo "== chat-alive rule and chat Langfuse traces (deterministic, free) =="
free test_chat_observability
echo "== recap headlines accept both CHANGELOG heading forms (deterministic, free) =="
free test_recap_headlines
echo "== regression suite: past mistakes stay fixed (bar: 100%) =="
"$PY" evals/run_regression.py --trials 3
echo "EVAL GATE: GREEN"
