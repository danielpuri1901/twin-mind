# LangSmith 3-layer evals: offline, online, flywheel

Date: 2026-07-24
Status: design, shape approved (Daniel, this session). Awaiting spec review before writing-plans.

## Goal

Move Twin from an offline-only eval setup to the industry-standard three-layer shape, all on LangSmith EU.
The three layers are: an offline regression gate, online production monitoring, and a flywheel that turns bad live runs into new test cases.
Second goal, equal weight: Daniel gets fluent in the LangSmith UI.
So the online, annotation, and alert layers are set up by Daniel in the UI, not scripted by the agent.

## Is this the industry standard (verified 2026-07-24)

This exact pattern is what Schneider Electric (60+ AI products, ~200 users) and Rippling (1M+ users) run in production, both on LangSmith.
Their own framing: observability, plus offline evals, plus online evals, plus production-traces-fed-back-into-datasets.
Rippling's layers map one-to-one to this design: offline on every commit, deploy-blocking online, continuous online against production.

Honest nuance: LangSmith is the standard specifically for LangChain and LangGraph native stacks.
Twin is framework-agnostic (raw Bedrock via boto3), so Langfuse (open source, self-host) and Braintrust (eval-first, used by Notion, Stripe, Vercel) are equally valid peers.
LangSmith is the right pick here for two reasons: it traces raw Bedrock cleanly via `@traceable` (verified in the docs), and it is the platform Daniel is targeting for the LangChain interview.

Data note: the one data-egress-conscious enterprise in the research (Schneider) self-hosted LangSmith rather than use SaaS.
Daniel chose LangSmith EU SaaS with full traces, a deliberate and scoped exception to the "off third-party storage" rule, recorded here.

## Architecture: everything keys off tracing

```
LIVE AGENT (box)  --trace-->  LangSmith EU (project: twin-mind)
  brief / prep / recap                 |
      |                                +- Layer 1 OFFLINE: per-agent golden dataset
      | writes fixture                 |     + eval.sh gate (blocks regressions pre-ship)
      |                                +- Layer 2 ONLINE: reference-free scorers on
      |                                |     every live run + drift alerts
      +- Daniel "verdicts?" reply --> feedback --+
                                                 |
                             Layer 3 FLYWHEEL: low score / bad verdict
                             -> annotation queue -> Daniel labels -> into the
                                golden dataset -> next gate tests today's failure
```

The single enabling primitive is tracing.
Once live runs are traced to LangSmith, all three layers hang off the same trace and dataset objects.

## The CODE vs UI split (deliberate, for the learning goal)

CODE (agent writes it):
- Turn on tracing in the live agents by wrapping the Bedrock `converse` call with `@traceable`.
- Offline: one eval module per agent plus a thin shared harness; retrofit the 8 silent judges to `structured_call`; delete the three non-LangSmith adapters.
- Wire the "verdicts" reply into a LangSmith feedback call on the run.

UI (Daniel does it, to build LangSmith fluency):
- Create the online evaluators on the twin-mind project (reference-free judge plus code validators), set sampling and filters.
- Set up an alert on score drift.
- Create the annotation queue, review flagged runs, one-click add-to-dataset.
- Read experiments and the monitoring dashboard.

## Layers

### Layer 1 - Offline, the gate (CODE)

One eval module per agent: `evals/brief_eval.py`, `retrieval_eval.py`, `prep_eval.py`, `recap_eval.py`.
A thin `evals/harness.py` does load -> run -> score -> `client.evaluate`.
Scorers are deterministic where possible (schema-valid, sections-complete in code) and a calibrated LLM-judge (via `structured_call`) for the open-ended parts.
This is where the eight silent judges get retrofitted from `except: return False` to a loud `structured_call`.
`eval.sh` runs them all plus the deterministic regression and fails on any drop.
Delete `evals/compare/braintrust_run.py`, `arize_run.py`, and the Langfuse mirror. LangSmith is the only platform.

### Layer 2 - Online, monitoring (UI, on top of CODE tracing)

Reference-free online evaluators on the twin-mind project: structural validity, a grounding and format policy check, a reference-free quality judge.
Scores every live run (sampling 1.0 to start, volume is low).
Opt out of extended trace retention per evaluator, to limit how long personal content persists and to control cost.
Alert when the low-score tail grows.

### Layer 3 - Flywheel (UI plus a little CODE)

The label mechanism already exists: the brief signs off with "Verdicts? (brief/coach/teacher: good|bad + notes)".
Wire that reply to a LangSmith feedback call on the run.
A low online score or a bad verdict routes the run into an annotation queue.
Daniel labels it, then one-click adds it to the agent's golden dataset with the label as reference.
Every bad morning becomes a permanent test case; no new habit required.

## How we build each judge + the flywheel (canonical method, verified 2026-07-24)

Four sources converge on the same method: Hamel Husain's LLM-as-judge guide, Anthropic's "Demystifying evals for AI agents", OpenAI's "evaluation flywheel" cookbook, and LangChain's Align Evals.
LangSmith productizes this exact loop as its "Align Evals" feature: annotation queue, then evaluator playground, then an alignment score.
It is UI-driven, so Daniel runs it in the UI.

The method, and how it maps to Twin:

1. One principal domain expert is the ground truth. That is Daniel.
His "verdicts?" replies are the gold labels; no abstract rubric outranks his call.

2. Look at the data before writing any criteria.
You cannot write a good judge prompt in advance; the act of grading real briefs is what defines the criteria (Shankar et al.'s "criteria drift").
So step one is Daniel reading real traces in LangSmith, not designing rubrics.

3. Binary pass/fail plus a written critique, never a 1-5 scale.
A "3 out of 5" is not actionable.
Each judge returns the critique first, then a pass/fail. This is already the shape in the per-section plan ({reasoning, verdict}).

4. The few-shot examples are the real judge, not the system prompt.
Keep each judge's instructions almost neutral; the power is 3+ concrete labeled examples drawn from Daniel's own critiques.
The dataset is the judge.

5. One judge per failure mode, tightly scoped.
Do not build one judge that grades everything.
This is exactly the open plan to split the blended brief judge into five per-section judges (triage, ai_news, teacher, coach, overall), now validated by the research.

6. Align each judge to Daniel's labels, then measure it honestly.
Label ~30 diverse examples, balanced across pass and fail.
Iterate the judge prompt until it agrees with Daniel (Hamel hit >90% agreement in three rounds).
Measure precision and recall separately (TPR and TNR), never raw agreement: the data is imbalanced, and a judge that always says "pass" looks 95% accurate while catching nothing.
Report on held-out examples so overfitting cannot fool you.
LangSmith Align Evals runs this whole loop in the UI and shows the alignment score.

7. Error analysis drives what to build next.
Read ~50 failing traces, open-code each failure in a word or two, cluster the codes into a taxonomy, count frequency, and prioritize by frequency times severity times impact.
The top clusters tell you which specialized judge to build; you do not invent judges speculatively.

8. The flywheel: a bad live run goes to the annotation queue, Daniel labels and critiques it, it lands in the golden dataset as a regression case and in the judge's few-shot set, then the judge is re-aligned.
Every fixed failure becomes a permanent test and a sharper judge.

## Evaluating the brief: decompose, classify, then dataset

Applying the deep-research-agent eval framework (Daniel's ArcelorMittal work, grounded in the deep-research benchmark literature) to the brief.
The brief is not a research agent, but it has the same shape: inputs in, a multi-section output out.
So we evaluate it the same way: decompose into sections, classify each section as deterministic or ambiguous and as having ground truth or not, and pick the grader from that classification.

| Section | Deterministic vs ambiguous | Ground truth | Grader |
|---|---|---|---|
| Date, weekday | Deterministic | Yes (the clock) | Code - injected, no judge |
| Format, dividers, sections present | Deterministic | Yes (the contract) | Code - schema_valid, sections_complete |
| "Reviewed N messages" | Deterministic | Yes (the count) | Code |
| needs_you_today, the yes/no decision | Deterministic | Yes (Daniel's actual inbox actions) | Code - verdict vs gold label (the triage regression) |
| needs_you_today, the phrasing | Ambiguous | No | Light LLM-judge |
| technical_thing, code_path + code_quote | Deterministic-checkable | Yes (the repo) | Code - the quote must appear verbatim in the file (anti-fabrication) |
| technical_thing, topic dedup | Deterministic | Yes (the covered list) | Code |
| technical_thing, concept + quiz quality | Ambiguous | No | LLM-judge aligned to Daniel |
| ai_advancements, not-already-covered | Deterministic | Yes (the covered list) | Code |
| ai_advancements, insight quality | Ambiguous | No | LLM-judge aligned to Daniel |
| coach, grounding + quality | Ambiguous | No | LLM-judge aligned to Daniel |

Two rules from the framework, both adopted:
- Grader choice follows the classification: checkable ground truth gets a deterministic check that runs on 100% of runs; genuine ambiguity gets an LLM-judge aligned to Daniel and run on a sample.
- Deterministic factual checks are not optional. The literature's recurring finding is that better instruction-following does not mean higher factual accuracy - agents fabricate confidently. For the brief this means the technical_thing code_quote must be verified against the real file; a holistic judge would happily pass a fabricated quote. This is a new Phase 1 check.

Per-section vs total datasets (the "per-subcategory or total" question): both, but built in order.
- The total, end-to-end dataset (morning-brief) stays - it catches a valid-looking combination of sections that is collectively wrong, and it carries the deterministic structural checks.
- Per-section datasets (brief-<section>-verdicts) are built only where error analysis shows a section is weak. teacher at 33% earns its own dataset and fix loop now; coach at 91% does not yet. This is "start end-to-end, do error analysis, build component datasets only where it breaks."

Flywheel tie-in: the decomposition is what lets the flywheel localize.
A bad brief's per-section scores say which section failed.
The deterministic parts of that section (quote-real, topic-duplicated) are auto-scored on every run; the ambiguous parts (concept, coach) route to the annotation queue.
The failing row grows that section's dataset and few-shot set, and the same per-section rubric runs offline in the CI gate and online on sampled traffic.
Always per-section scores, never one aggregate - an aggregate 85% hides teacher's 33%.

## The watchdog and the online layer: division of labor

The brief already has a watchdog (a box-side cron that caught the "Friday 25 July" date bug).
It overlaps with the new online deterministic evaluators, so their roles are split by dependency and purpose, and the check logic is defined once.

Define every deterministic check once, in `evals/brief_checks.py`, as pure functions (schema_valid, format_ok, date_correct, quote_is_real, topic_not_duplicated).
Two classes, by what the check needs:
- Needs box state (the repo, the covered files, "did it even run") -> runs on the box, in the watchdog.
- Needs only the trace inputs and outputs (schema, format, sections present) -> runs server-side, as a LangSmith online code evaluator.

Roles:
- Watchdog = the dead-man's alarm. Independent of LangSmith, runs shortly after the 07:30 brief, alerts Daniel on Telegram immediately if the brief is broken or did not run. It must not depend on LangSmith, so it still fires if tracing is down. Best-effort, it also pushes its verdicts to the LangSmith run as feedback so the flywheel sees them.
- LangSmith online evaluators = the quality, drift, and flywheel layer. Reference-free deterministic checks on trace I/O run on 100% of runs; the ambiguous LLM-judges run on a sample. Alerts via LangSmith, feeds the annotation queue.

Timing per morning: 07:30 brief runs -> sends and traces. LangSmith online evaluators fire on the trace automatically. The watchdog fires shortly after -> Telegram alarm if broken, plus a best-effort feedback push.

Phase tie-in:
- Phase 1 refactors the existing watchdog to import the shared `brief_checks.py` (single source of truth), instead of its own copies.
- Phase 2 registers the trace-I/O checks and the judges as LangSmith online evaluators, and wires the watchdog's feedback push.
- Phase 3 routes the failing runs (from either source) into the annotation queue and dataset.

The watchdog is not replaced. It is promoted to the independent liveness alarm and a feedback source, with its check logic unified with the offline and online layers.

## Build phases (each ship-gated; eval.sh stays green)

Phase 0 - Tracing on.
Wrap the live agents' Bedrock calls with `@traceable`, set the env on the box, confirm live briefs appear as traces in the twin-mind project.
Small, high-leverage, unlocks Layers 2 and 3.

Phase 1 - Offline consolidation and judge alignment.
One-eval-per-agent plus harness; retrofit the eight judges to `structured_call` returning {critique, verdict}; split the blended brief judge into the five per-section judges (the existing plan); align each judge to Daniel's labels via LangSmith Align Evals until agreement holds (precision and recall, on held-out examples); drop the three adapters; eval.sh green.

Phase 2 - Online evaluators (Daniel in the UI).
Reference-free judges plus code validators on twin-mind; sampling 1.0; opt out of extended retention; one alert.

Phase 3 - Flywheel.
Annotation queue (UI); "verdicts" reply to feedback (CODE); add-to-dataset and add-to-few-shot flow.
Plus a recurring error-analysis pass: open-code ~50 failing traces, cluster into a taxonomy, prioritize, and build the next specialized judge only where the data demands it.

## Data residency

Full traces, including personal content, go to LangSmith EU (eu.smith.langchain.com, eu.api.smith.langchain.com).
This is a documented exception to the off-third-party-storage rule, scoped to LangSmith EU.
Opt out of extended trace retention on the online evaluators to bound how long personal content persists.

## Out of scope (each its own follow-up)

- The chat agent (interactive, a different eval shape).
- Self-hosting LangSmith.
- Moving off Bedrock.

## Success criteria

- Live brief, prep, and recap runs are traced to LangSmith.
- `eval.sh` is the gate, one clean eval module per agent, judges no longer silently default.
- Each judge is aligned to Daniel's labels and reported with precision and recall on held-out examples, not raw agreement.
- Online evaluators score live runs, and one alert is configured by Daniel in the UI.
- One full flywheel loop demonstrated: a bad live run, annotated, added to the golden dataset, caught by the gate.

## References (verified 2026-07-24)

- Hamel Husain, "Creating a LLM-as-a-Judge That Drives Business Value" (hamel.dev/blog/posts/llm-judge).
- Anthropic, "Demystifying evals for AI agents" (anthropic.com/engineering).
- OpenAI Cookbook, "Building resilient prompts using an evaluation flywheel" (open coding, axial coding, TPR/TNR, train/val/test split).
- LangChain, "How to Calibrate LLM-as-Judge with Human Corrections" and the LangSmith Align Evals docs.
- Production references for the three-layer shape: Schneider Electric and Rippling LangSmith case studies.
