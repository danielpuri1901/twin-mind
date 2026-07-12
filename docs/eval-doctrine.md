# Eval doctrine: how we run online evals (adopted 2026-07-12)

We follow two LangChain articles, translated to a one-user agent (~10 traces/day):
- "Agent Observability: How to Monitor and Evaluate LLM Agents in Production" (blog/production-monitoring)
- "Evaluating AI Agents at the Run, Trace, and Thread Level" (resources/agent-evals)

| Their practice | Our translation | Status |
|---|---|---|
| Run / trace / thread primitives | Langfuse runs+traces; Telegram session = thread | have |
| Deterministic checks on 100% of traffic | brief_check.py at 07:50: outcome (email exists, heartbeat emitted) + format contract + coverage line | BUILD next |
| LLM judges on sampled traces (10-20%) | at our volume 100% costs ~$0.02/day: teacher + coach rubric judges, nightly | after calibration |
| Judge calibration vs human labels (20+ labels, track agreement, recalibrate on schedule) | Daniel's daily verdicts ARE the labels. After ~20 verdicts: run judges on the same briefs, measure agreement, fix RUBRIC on disagreement (never the human). Recalibrate monthly. | doctrine |
| Annotation queues | n=1 version: (a) the daily verdict reply, (b) weekly review - twin surfaces unrated briefs, judge-vs-Daniel disagreements, flagged traces in ONE Telegram message; Daniel labels in-line | BUILD (skill) |
| One-click trace->dataset | one-APPROVAL: any "bad + note" verdict makes the twin DRAFT a regression item from the trace; Daniel approves; item lands in the dataset | BUILD (skill) |
| Escalate: cheap checks always, LLM judge only on dips | adopt at scale; for now judges run daily (cost trivial) | doctrine |
| Alert thresholds | dead-man (have) + brief_check failure -> Telegram alert + 2 consecutive "bad" verdicts on a section -> flag in next brief | BUILD-lite |
| Thread-level evals | tau2-style fixture scenarios (queued as run_regression --agent) | queued |
| Insights / pattern mining | monthly pass over feedback.jsonl + traces; findings become dataset items or skill changes | doctrine |

Their 3-step adoption path, our position: (1) foundation = done; (2) gate releases on regression = done (eval.sh); (3) monitor continuously = THIS quarter's work, in the order above.

Rules that survive any tooling change:
1. Deterministic checks are free - they run on everything, always.
2. A judge is only as good as its agreement with Daniel - calibrate before trusting, recalibrate on schedule.
3. Every "bad + why" becomes a dataset item within a day. Bugs stay fixed because they become tests.
4. Capture at section granularity; aggregate for trends. Never capture pre-aggregated.
