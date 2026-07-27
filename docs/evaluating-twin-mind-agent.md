# Evaluating the Twin Mind Agent: A Production Blueprint

This is the Twin Mind version of the two AWS Strands eval guides, applied to our own project.
It keeps the same structure, the same number of evaluators (10), and the same practice - build-time offline gate plus production monitoring - but adapted to what the Twin actually is.
The Twin is not a car-search agent with money on the line.
It is a personal capture, recall, and reflection agent that lives on Telegram and is grounded in Daniel's own corpus.
That changes what "failure" means, so it changes the evaluators.

---

## The challenge

The Twin is the memory of your own life.
You dump novel ideas, work learnings, and reflections into it, and you ask it to recall them later.
The danger is not a wrong car listing.
The danger is that it quietly distorts or invents one of your own facts, drops half of a fragmented note, or gets the date wrong - and you trust it anyway.

Three things make this hard to test the normal way.

The output is non-deterministic, so the same input can produce different replies.
The usage is sporadic and volatile, so live statistical sampling is mostly noise.
Most turns are private reflection, so what we send to a judge or to a platform is a real decision, not a default.

## The approach: two phases, adapted for sporadic volume

We keep the AWS two-phase shape.

Build-time evaluation catches regressions before a change ships, using a curated golden set as a CI gate.
Production monitoring catches what the golden set misses, using cheap deterministic checks on every turn plus your explicit thumbs.

The one adaptation: because your volume is sporadic, the **offline** evaluation path is primary, not the live one.
We evaluate your recorded history, not a live sample.
The live sampled judge stays off until the Twin gets heavy daily use.

## Why evaluating the Twin is different

LLM evaluation asks whether a single reply reads well.
Agent evaluation asks whether the whole interaction did its job over many turns and tool calls.
For the Twin, the dimensions that matter are these.

| Dimension | Why it matters for the Twin |
| --- | --- |
| Capture fidelity | it is your memory - a distorted capture corrupts your own record |
| Groundedness | the corpus skill's first rule is "never invent a personal fact" |
| Recall accuracy | "when did I..." must find the real entry and cite it, not hallucinate |
| Temporal correctness | date and time errors are a recurring, observed failure |
| Response register | when you are capturing, a monologue back is the wrong response |
| Reliability | non-determinism means one good run does not prove the next |
| Privacy | most turns are private, so judge exposure is a scoped choice |

## Core concepts, mapped onto our stack

The AWS guide has three primitives: Case, Experiment, Evaluator.
We already have all three under different names, so we adopt the vocabulary rather than the library.
Note that `strands-agents-evals` only runs on the Strands SDK; the Twin is Hermes, so we take the practice, not the package.

| AWS Strands | Twin Mind equivalent | What it is |
| --- | --- | --- |
| `Case` | one golden-set row | `{input, expected_output, expected_trajectory, metadata}` |
| `Experiment` | `align.py` + `client.evaluate` | runs the cases, applies evaluators, reports |
| `Evaluator` | `judges.py` + `brief_checks.py` | the scoring logic, code or judge |
| `Task Function` | our `target(inp)` | connects the agent's run to the evaluator |

## The Task Function: offline over your own history

This is the piece that fits your sporadic usage, and it is straight from the AWS guide.
An offline Task Function does not invoke the agent live.
It loads a previously recorded trace, maps it into the shape the evaluators expect, and returns it for scoring.

For the Twin, the trace store is the box's `state.db` - 40 sessions, 114 real Telegram turns.

```python
# offline task function - evaluate history, not a live sample
def twin_task(case):
    trace = load_trace_from_state_db(case.session_id)   # the real conversation
    return {
        "input": case.input,
        "final_response": extract_assistant_reply(trace),
        "trajectory": extract_tool_calls(trace),         # what it did (corpus-search, notion, ...)
        "retrieved_context": extract_corpus_hits(trace), # the source, for faithfulness
    }
```

The same evaluators and the same gate run whether the case came from history or from a live CI run.
The Task Function is the only thing that changes between the two.

## The ten Twin Mind evaluators

The AWS guide ships ten built-in evaluators.
We define ten too, mapped one-to-one, adapted to the Twin, and dropping the ones that do not apply in favor of ones that match our real failures.
Scoring stays **binary plus a written critique**, not the 5- or 7-point scales AWS uses, because binary is what aligns to your labels via precision and recall.

| # | Twin evaluator | Type | What it checks | Level | AWS parallel |
| --- | --- | --- | --- | --- | --- |
| 1 | `faithfulness` | judge | every claim is grounded in your corpus; never invents a personal fact | trace | FaithfulnessEvaluator |
| 2 | `capture_saved` | code | the note/idea was actually written to journal / Notion / memory | tool | ToolSelectionAccuracy |
| 3 | `capture_completeness` | judge | the whole fragmented dump was captured, nothing dropped | session | (new - Twin-specific) |
| 4 | `capture_fidelity` | judge | it recorded what you said, correctly attributed (the Karpathy case) | trace | OutputEvaluator |
| 5 | `recall_grounded` | code + judge | "when did I..." cites a real corpus entry, does not hallucinate | trace | FaithfulnessEvaluator |
| 6 | `corpus_search_used` | code | it ran `corpus-search` (via terminal) when the question needed the corpus | tool | ToolSelectionAccuracy |
| 7 | `query_quality` | code + judge | the corpus-search query / save arguments were right | tool | ToolParameterAccuracy |
| 8 | `helpfulness` | judge | it addressed what you actually wanted, right register (note vs monologue) | trace | HelpfulnessEvaluator |
| 9 | `temporal_correct` | code | the date / time it used was correct | trace | (new - Twin-specific) |
| 10 | `goal_success` | judge | the whole conversation achieved your intent | session | GoalSuccessRateEvaluator |

Two production monitors run outside the ten, on 100% of turns, because they are free and need no labels: `compression_ok` (the context-compression failure seen in 16 of 40 sessions) and `safe_output` (no PII or secret leak).
These map to the AWS HarmfulnessEvaluator and to reliability monitoring.

## Evaluation levels: the same hierarchy

The Twin evaluators sit at the same three levels AWS uses.

Session level looks at the whole conversation: `goal_success`, `capture_completeness`.
Trace level looks at one turn: `faithfulness`, `capture_fidelity`, `recall_grounded`, `helpfulness`, `temporal_correct`.
Tool level looks at one tool call: `capture_saved`, `corpus_search_used`, `query_quality`.

You compose a suite across levels so a single run checks the tool calls, the turn, and the whole goal at once.

## Ground truth

Each Case can carry `expected_output` and `expected_trajectory`, exactly as in Strands.
For a capture case, the expected trajectory is "a save tool was called" and the expected output is "a brief confirmation, not a monologue."
For a recall case, the expected output is the real corpus fact plus a citation.
Not every case needs every field; you set the expectation that matters for that case.

## The diff: AWS Strands versus Twin Mind

| Concept | AWS Strands | Twin Mind | Verdict |
| --- | --- | --- | --- |
| Framework | Strands SDK + strands-agents-evals + Bedrock AgentCore | Hermes + `align.py` / `judges.py` + LangSmith | adopt the practice, not the library |
| Case | `strands_evals.Case` | golden-set row, same schema | same |
| Experiment | `Experiment` | `align.py` `client.evaluate` | same |
| Task Function | online or offline | offline over `state.db`, primary | adapted (offline-first for sporadic use) |
| Scoring | scales (7-point, 5-point) | binary + critique | changed (binary aligns to labels) |
| Production monitoring | AgentCore Evaluations, sampled | deterministic on 100% + thumbs | adapted (no live sampling at low volume) |
| Multi-turn testing | `ActorSimulator` | deferred | dropped for now (overkill at low volume) |
| Metric | pass^k | pass^k, n >= 3 | same |
| Gate | 3-layer, >95 / >85 / >90 | 3-layer, per-dimension floors vs baseline | same shape |
| InteractionsEvaluator | multi-agent | not used | dropped (no multi-agent in chat) |

The headline: the practice transfers almost unchanged.
What changes is the substrate (Hermes not Strands, LangSmith not AgentCore), the scoring (binary not scales), and the primary path (offline over history, because your usage is sporadic).

## The gate

A change to a prompt, a skill, or a tool schema must pass the gate before it ships, exactly like a failing test.
The gate runs the ten evaluators over the golden set and blocks if any dimension drops below its floor.
It reports per dimension, never as one average, so a strong `helpfulness` can never hide a weak `faithfulness`.
It uses pass^k over at least three trials, because one trial of a non-deterministic agent is a sample of size one.

## The build

1. Clean the eval tree and ship plugin v2 (ordered trajectory, tokens, turn-success), so traces are eval-grade.
2. Mine your 114 real turns into `Case` rows, bucketed by intent (capture, recall, reflect), and label the first ~30-50 in the LangSmith UI.
3. Wire the offline Task Function over `state.db` and the ten evaluators into `align.py`, and run the first gate.
4. Turn on the two production monitors (`compression_ok`, `safe_output`) on 100% of turns, and the thumbs signal.
5. Grow the golden set from thumbs and flagged turns; add the online sampled judge only once volume rises.

## Grounding

This blueprint is grounded in your own data (40 sessions on the box, 114 real turns, 16/40 compression failures, corpus reached via `corpus-search`), in the codebase inventory, and in frontier practice.
The frontier sources: Anthropic "Demystifying Evals for AI Agents"; the two AWS Strands guides plus Bedrock AgentCore Evaluations; LangSmith agentevals and multi-turn online evaluations; FutureAGI and ContextOS on golden-set design; tau-bench and tau2-bench for pass^k; AgentRedBench for injection red-teaming.
The deterministic-first grader ladder holds throughout; it was only ever applied to the wrong target before.
