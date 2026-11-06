# ARM64 image for Twin Mind's scheduled jobs. GitHub Actions builds it. The laptop never does.
#
# Stage layout:
#   base  - Python, the pinned packages and the AWS CLI the jobs call for heartbeats and S3 sync.
#   code  - base plus the repo code.
#   test  - code plus the free tests. Nothing here ships.
#   final - code, and only if the tests passed.
#
# State, .env and the corpus stay on the host and are mounted at the same paths the code expects,
# so the image holds no secrets and no personal data. HOME matches the box, and the user id matches
# the box's job user, so mounted files keep the right owner.
# tzdata and TZ matter: without them ZoneInfo fails and meeting times silently come out wrong.
FROM python:3.11-slim-bookworm AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends awscli ca-certificates git tzdata \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 1000 --create-home --home-dir /home/ec2-user ec2-user
COPY infra/box-requirements.txt /tmp/box-requirements.txt
RUN pip install --no-cache-dir -r /tmp/box-requirements.txt && rm /tmp/box-requirements.txt
ENV HOME=/home/ec2-user PYTHONUNBUFFERED=1 TZ=Europe/Luxembourg
WORKDIR /app

FROM base AS code
COPY agents /app/agents
COPY shared /app/shared
COPY pipeline /app/pipeline
COPY evals /app/evals
COPY docs/CHANGELOG.md /app/docs/CHANGELOG.md
COPY infra/bin /app/infra/bin

FROM code AS test
USER ec2-user
RUN mkdir -p "$HOME/.twin-mind/state" && touch "$HOME/.twin-mind/.env"
RUN set -e; for t in test_tools test_project_activity_collector test_project_activity test_compose_brief test_prep_scan test_brief_check test_wispr_ingest test_recap_meetings test_corpus_sync test_corpus_parity test_compose_prep test_corpus_rag_stats test_chat_observability test_recap_headlines test_embedding_contract; do echo "== $t"; python "evals/$t.py"; done; touch /tmp/tests-passed

FROM code AS final
# This line makes the build run the test stage, so a failing test stops the push.
COPY --from=test /tmp/tests-passed /tmp/tests-passed
USER ec2-user
