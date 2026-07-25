# LangSmith 3-layer evals - Implementation Plan (Phases 0-1)

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Get Twin's live agents tracing to LangSmith (Phase 0), then consolidate the offline evals into one-per-agent with loud structured judges aligned to Daniel's labels (Phase 1).

**Architecture:** Tracing is added at two levels - `structured_call` (every constrained LLM call becomes a span) and each agent's top entry (the whole run becomes one trace). Offline evals collapse to one module per agent over a thin shared harness, judges become `structured_call` returning {critique, verdict}, and each judge is aligned to Daniel's labels in the LangSmith Align Evals UI.

**Tech Stack:** Python, boto3 Bedrock Converse, LangSmith SDK (`langsmith`), Pydantic, Hermes cron on AWS EC2 (SSM-only).

## Global Constraints (verbatim, apply to every task)

- Ship gate: `evals/eval.sh` green (triage regression 100%) before ANY deploy to the box. No exceptions.
- Repo -> box is one-way over SSM. Twin never self-edits skills. Deploys are human-run from the Mac.
- AWS auth is custom `aws login` (NOT SSO). The moment a flow hits AWS session expiry: STOP and flag Daniel, never touch credentials.
- Data residency: full traces (incl. personal content) to LangSmith EU is the approved, scoped exception. Endpoint `eu.api.smith.langchain.com`, project `twin-mind`. Nothing corpus-related to any OTHER third party.
- Never break the live brief (`morning-brief-v4` cron / `compose_brief.py`). Pause-don't-delete on any cron swap.
- Timezone: pin `Europe/Luxembourg` for any date/weekday logic.
- No em dash (use "-"). No auto-commit (Daniel commits). No AI vocab.

---

## Phase 0: Tracing on

### Task 0.1: Verify box reachability + env (execution prereq)

**Files:** none (read-only checks on the box).

- [ ] **Step 1: Confirm AWS session is alive.** Run `aws sts get-caller-identity`. Expected: JSON with the account/role. If it errors with expired/invalid token, STOP and ask Daniel to run `aws login`, then resume.
- [ ] **Step 2: Confirm the box has the LangSmith env.** Via SSM, read `~/.hermes/.env` for `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT`, `LANGSMITH_PROJECT`. Expected: key present (the A/B used it); endpoint should be the EU one; project should be `twin-mind`. Note any missing keys for Task 0.4.

### Task 0.2: Trace every constrained LLM call

**Files:** Modify `shared/structured.py`.

**Interfaces:** Produces: `structured_call(...)` unchanged signature, now emitting a LangSmith span named after the schema when `LANGSMITH_TRACING=true`, a no-op otherwise.

- [ ] **Step 1: Add the import and decorator.** At the top of `shared/structured.py`, add `from langsmith import traceable`. Decorate `structured_call` with `@traceable(run_type="llm", name="structured_call")`. The langsmith SDK auto-no-ops when `LANGSMITH_TRACING` is unset, so eval and offline runs are unaffected unless they opt in.
- [ ] **Step 2: Local smoke test (tracing OFF).** Run a one-liner that calls `structured_call` on a tiny schema with `LANGSMITH_TRACING` unset. Expected: returns the validated model, no network to LangSmith, no error. This proves the decorator is inert when off.

### Task 0.3: Trace each live agent as one run

**Files:** Modify `agents/brief/tools/compose_brief.py`; `agents/background-prep/tools/<compose entry>.py`; `agents/weekly-recap/tools/<compose entry>.py`.

**Interfaces:** Produces: each agent's top compose entry wrapped so a full run is a single parent trace tagged with the agent name.

- [ ] **Step 1: Brief.** In `compose_brief.py`, add `from langsmith import traceable` and decorate `compose(facts)` with `@traceable(name="brief.compose", tags=["agent:brief", "env:prod"])`. Do NOT wrap `main()` (keep send/side-effects out of the traced unit).
- [ ] **Step 2: Prep + recap.** Find the equivalent single compose function in background-prep and weekly-recap (the one that calls the model). Decorate each with `@traceable(name="<agent>.compose", tags=["agent:<name>", "env:prod"])`. If an agent has no single compose function yet (still agent-loop style), note it and defer that agent to Phase 1 rather than forcing a wrap.
- [ ] **Step 3: Local dry-run of the brief (tracing OFF).** Run `python3 agents/brief/tools/compose_brief.py --dry-run` on the Mac with tracing unset. Expected: composes and prints a brief, no errors. Proves the decorators didn't break composition.

### Task 0.4: Turn tracing on in the box env

**Files:** Modify `~/.hermes/.env` on the box (via SSM, human-run).

- [ ] **Step 1: Set the flag.** Ensure `~/.hermes/.env` contains `LANGSMITH_TRACING=true`, `LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com`, `LANGSMITH_PROJECT=twin-mind`, and the existing `LANGSMITH_API_KEY`. Add any that Task 0.1 found missing.
- [ ] **Step 2: Confirm no secret leaves the Mac.** The `.env` edit happens on the box; do not copy the key anywhere else. Confirm `.env` is not tracked by git (`git check-ignore ~/.hermes/.env` is not applicable on the box; verify the repo `.gitignore` still excludes any local `.env`).

### Task 0.5: Ship gate, then deploy the two code files

**Files:** deploy `shared/structured.py` + the decorated agent files to the box.

- [ ] **Step 1: Ship gate.** Run `evals/eval.sh`. Expected: GATE GREEN (triage regression 100%). Tracing is additive; if the gate is red, STOP and fix before deploying.
- [ ] **Step 2: Deploy (one-way, SSM).** Push the changed files to the box the same way prior deploys ran (repo -> box). Do not deploy `.env` (Task 0.4 handled it on the box).

### Task 0.6: Verify a real trace lands

**Files:** none (verification).

- [ ] **Step 1: Trigger a traced run on the box.** Run the brief in dry-run on the box with the box env sourced: `LANGSMITH_TRACING=true ... python3 .../compose_brief.py --dry-run`. Dry-run still calls the model, so it still traces, without sending an email.
- [ ] **Step 2: Confirm in LangSmith (UI, Daniel).** Open the `twin-mind` project at `eu.smith.langchain.com`. Expected: a new trace named `brief.compose` with a child `structured_call` span, tagged `agent:brief`. If it appears, Phase 0 is done.
- [ ] **Step 3: Append a dated CHANGELOG entry** to `docs/CHANGELOG.md` describing tracing-on. Do not commit (Daniel commits).

---

## Phase 1: Offline consolidation + judge alignment

**File structure (target):**
- Create `evals/harness.py` - shared: load golden -> run target -> score -> `client.evaluate`. One place.
- Create `evals/brief_eval.py`, `evals/retrieval_eval.py` (fold in generation), `evals/prep_eval.py`, `evals/recap_eval.py` - one per agent; each declares its golden dataset name + scorers + `main()`.
- Modify `evals/eval.sh` - run each per-agent eval + the deterministic regression; fail on any drop.
- Delete `evals/compare/braintrust_run.py`, `evals/compare/arize_run.py`, `evals/push_to_langfuse.py` (LangSmith is the only platform).
- Retrofit judges: `evals/generation_eval.py` `_judge`, `evals/run_regression.py` graders, `evals/run_brief_bench.py` judge, `evals/compare/eval_task.py` `judge_one`/`judge_section`, `evals/calibrate_judges.py`, plus the existing `evals/retrieval_eval.py` `llm_supported`.

### Task 1.1: Retrofit the ship-gate graders first (highest blast radius)

**Files:** Modify `evals/run_regression.py`.

- [ ] **Step 1:** Define a `Verdict(BaseModel)` with `critique: str` (first) and `passed: bool`. Replace each `prompt-for-JSON + regex + except: return False` grader with `structured_call(MODEL, sys, user, Verdict)`; on exception let it RAISE (loud), do not default.
- [ ] **Step 2:** Run `evals/eval.sh`. Expected: GATE GREEN, identical pass/fail to before (behavior preserved, failure now loud). If a run raises, that is a real judge failure to inspect, not to swallow.

### Task 1.2: Split the blended brief judge into per-section judges

**Files:** per the existing plan `~/.claude/plans/hazy-watching-flute.md` (already drafted): `evals/compare/eval_task.py` (`section_rows`, `SECTION_JUDGES`, `judge_one`) + `evals/calibrate_sections.py`.

- [ ] **Step 1:** Implement the five per-section judges (triage, ai_news, teacher, coach, overall), each `structured_call` returning {critique, verdict}, criteria lifted verbatim from `calibrate_judges.py`.
- [ ] **Step 2:** Run `evals/calibrate_sections.py`. Expected: five agreement numbers; sanity-check vs the known per-section values (triage 83 / ai_news 92 / teacher 33 / coach 91 / overall 50). Large divergence -> reconcile.

### Task 1.3: Align each judge to Daniel's labels (LangSmith Align Evals, UI)

**Files:** none (LangSmith UI + the labeled dataset).

- [ ] **Step 1 (Daniel, UI):** In the `morning-brief` / `brief-<section>-verdicts` datasets, run an experiment, send runs to an annotation queue, label ~30 diverse examples balanced pass/fail.
- [ ] **Step 2 (Daniel, UI):** In the Evaluator Playground, iterate each judge prompt until the alignment score holds; measure precision + recall separately, report on held-out examples. Save the aligned prompt.

### Task 1.4: Consolidate to one-eval-per-agent + drop the other platforms

**Files:** create `evals/harness.py` + the four `*_eval.py`; modify `eval.sh`; delete the three adapters.

- [ ] **Step 1:** Write `harness.py` (load/run/score/evaluate), then the four per-agent eval modules that call it. Each runnable standalone AND from `eval.sh`.
- [ ] **Step 2:** Point `eval.sh` at the four modules + the deterministic regression. Delete `braintrust_run.py`, `arize_run.py`, `push_to_langfuse.py`.
- [ ] **Step 3:** Run `evals/eval.sh`. Expected: GATE GREEN. Append a dated `docs/CHANGELOG.md` entry. Do not commit.

---

## Phases 2-3 (planned after Phase 0 is live)

Online evaluators (Phase 2) and the annotation-queue flywheel (Phase 3) are UI-driven and need live traces to exist first. They get their own plan once Phase 0 verifies traces are landing. The method is fixed in the design doc (binary pass/fail + critique, few-shot-as-judge, precision/recall, error analysis -> specialized judges).

## Self-review notes

- Spec coverage: Phase 0 covers "tracing on"; Phase 1 covers offline consolidation + judge retrofit + per-section split + alignment; Phases 2-3 deferred with a pointer. All spec success criteria except the online/flywheel ones are addressed here.
- The Phase 1 per-section split reuses the already-approved `hazy-watching-flute.md` plan rather than duplicating it.
