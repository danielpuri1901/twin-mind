# Eval doctrine

Reset on 2026-11-06. Daniel removed the LLM judges, the benches and their calibration sets.

They ran, but they changed nothing.
The record on the day of the reset:

- `insight_is_real` averaged 0.485 over 132 LangSmith runs, and its calibration gate read 0.76 against a floor of 0.85.
- `coach_faithfulness` and `insight_is_real` both failed all 2 briefs scored in Langfuse, and no person was told.
- `sections_present` averaged 0.484 over 126 LangSmith runs, and no person was told.
- `no_em_dash` averaged 1.0 over 126 runs, so it never flagged anything.

## The rule for a new check

A check earns its place only if all four are true:

1. It measures a real outcome, or a failure that no person would see.
2. It runs without a person, or it blocks a build.
3. A failure reaches Daniel on Telegram or stops the build. A score on a dashboard does not count.
4. It failed once on purpose, to prove that the failure path works.

## What remains

| Check | What it catches | How it tells |
|---|---|---|
| Free tests in `evals/test_*.py` | Past bugs coming back. | Blocks the image build in CI |
| `agents/brief/tools/brief_check.py` | The brief did not arrive, or broke its format | Telegram alert at 07:50 |
| `shared/corpus_staleness.py` | Corpus data stopped arriving | Telegram alert |
| `infra/bin/chat_alive.py` and the `twin-mind-chat-deadman` alarm | Chat stopped | CloudWatch alarm |
| `agents/chat/tools/corpus_context.py` | Auto-retrieval crashes, reported as an error and never read as empty | Telegram alert each hour |
| `evals/run_regression.py` | Past triage mistakes after a prompt or model change | Red gate, run by hand through `evals/eval.sh` |
| `evals/longmemeval_retrieval.py`, `evals/retrieval_eval.py` | Retrieval got worse after a retrieval change. The first caught a change that took recall from 0.92 to 0.84. | By hand, before a retrieval change |

`evals/costs.py` is a cost report, not a check.

## What comes next

New checks start from real failures and silent failures: memory drift, Letta dreaming, retrieval drift, and harness or model upgrades.
Each one must pass the rule above before it ships.
