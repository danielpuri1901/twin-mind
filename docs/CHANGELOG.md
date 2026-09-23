# Twin Mind - canonical changelog
One dated entry per working session. Newest on top. The full narrative lives in RETROSPECTIVE.md; this file is the terse ledger.

## 2026-09-23 - meetings move from Granola to Wispr Flow; prep sends one message, not three

Daniel reported the prep "running twice": a message the day before and the correct one before the meeting.
Root cause, confirmed in the box logs, Bedrock invocation logs and a read-only replay against the live calendar: there was one poller and one dossier run per meeting.
The poller runs as a no-agent cron, so its own stdout is a Telegram message.
The 21:00 goal question (day before) and the "prep scheduled" status line (T-75) both reached Telegram and read as extra preps.

### LEARNINGS TODAY - by subject (teach whichever is not yet on the taught list)

**1. In a no-agent cron, every print is a user-facing message**
`scan_meetings.py` now prints only failures.
The 21:00 goal question and the success status line are removed.
3 new fixtures in `evals/test_prep_scan.py` pin it (29 total).

**2. Use the vendor's official integration, and check which way it moves data**
Wispr Flow Notetaker has no webhooks, no Zapier app and no REST API.
The only integration is a read-only remote MCP (`https://api.wisprflow.ai/connect/mcp`), so the box pulls.
New `pipeline/ingest_wispr_meetings.py` replaces the Granola summary ingester: verbatim transcript plus summary per meeting, windowed and context-prefixed like the rest of the corpus, incremental inserts only.
Long summaries split at `###` sections so nothing is cut at the 2048-char embed cap.
Backfill: 9 meetings, 225 records, 0 failures; a second run is a no-op.
`corpus-search` returns the right meeting in the top 3 for an interview-case query and a client-debrief query.

**3. A heartbeat proves the job ran, not that data arrived**
The box index had not changed since Jul 21: the Granola ingester kept heartbeating while it saved nothing, so its alarm stayed green for two months.
The new ingester emits `MeetingIngestRan` (job ran) and `MeetingsIngested` (meetings saved).
Alarms: `twin-mind-meeting-ingest-deadman` (12h without a run) and `twin-mind-meeting-freshness` (7 days without a new meeting).

**4. One OAuth token family, one owner**
The Wispr Flow token lives only on the box (`wispr-ingest.json`), moved through a short-lived SecureString parameter, then deleted from the Mac.
A forced refresh on the headless box returned a new token and a rotated refresh token.

Also: weekly recap reads this week's meetings from `corpus.db` instead of a Mac folder (`evals/test_recap_meetings.py`, 8 fixtures).
Granola retired: Mac launchd poller unloaded, Mac and box Granola tokens and MCP entries removed, `fetch_granola.py`, `ingest_meeting_summaries.py` and their test deleted, old alarm deleted.
Prep skill searches corpus meeting history by name and company (Wispr Flow often labels speakers "Speaker 1/2").

Shipped to the box: poller fix, prep skill, ingester, recap, `summary-ingest.service` pointed at the new ingester; index backed up as `*.pre-wispr-20260923-112016`. eval.sh green.

## 2026-08-15 - novelty gate: the brief stops resurfacing the same AI items (semantic dedup in code)

The AI ADVANCEMENTS section kept saying the same stuff. Root cause: dedup was the model's job - a phrase list pasted into the prompt with "don't repeat" - which it rephrases around, and the injected tail scrolls off so old items cycle back.

### LEARNINGS TODAY - by subject (teach whichever is not yet on the taught list)

**1. Dedup is deterministic CODE, not the model's memory - filter before it sees the candidates**
New `shared/novelty.py`: an append-only store of what the brief ACTUALLY surfaced, each with its Cohere embedding; `filter_novel(candidates)` drops any candidate within cosine 0.80 of anything seen, so the model only ever sees survivors - it cannot repeat what it never sees.
Wired: `prefetch.ai_news()` filters the Tavily candidates; `compose_brief.main()` records the shipped insights after send.
Calibrated on real Cohere v3 scores: near-duplicate rephrasings land 0.90+, a genuinely-new development on a covered topic ~0.61, unrelated <0.45 - so 0.80 drops repeats with margin while keeping new developments. Fail-open (any embed error returns all candidates; never blocks the brief). Reusable - LeadSense calls the same `filter_novel` / `record`.

**2. Novelty needs a real feed; dedup only shapes what the feed brings in**
A filter removes repeats but can't manufacture new content from a fixed distribution. The Tavily feed (added 08-04) is the source; the novelty gate is the second half.

Shipped to the box: shared/novelty.py + prefetch/compose wire-ins; eval.sh green (9/9); prod verified (box gate drops a near-dup, keeps a novel item).

## 2026-08-12 - brief triages the inbox on full body + Gmail's own importance (stopped missing interview emails)

The brief missed a CharacterQuilt technical screen (Bhairav) and a LangChain recruiter reply (Tiff Bell) - both real, both in-window, both past the noise filter.
Root cause, confirmed by reading the actual Gmail: the brief handed the model only the SUBJECT line, and both subjects hid the ask (Bhairav's was bland; Tiff's still carried the stale July calendar-invite subject).

### LEARNINGS TODAY - by subject (teach whichever is not yet on the taught list)

**1. Triage on content, not the subject line - and don't throw away Gmail's own signal**
`agents/brief/tools/prefetch.py` `inbox` now pulls EVERY inbox item since the cursor (the substring noise skip-list - which could silently nuke a real email whose From header merely contained a noise word - is gone), each with a ~300-char HTML-stripped body snippet, plus Gmail's `\Starred` / `\Important` read via the X-GM-LABELS IMAP extension.
`compose_brief.py`'s needs_you_today rule now reads the body + Gmail-importance and is told the inbox is unfiltered so it ignores the now-visible marketing.
Verified live against the two missed emails: Bhairav surfaces via STARRED+IMPORTANT+body, Tiff via IMPORTANT+body. Cost of pulling all-with-bodies: ~1k tokens/brief (~12c/month) - a false positive is far cheaper than a silently-dropped technical screen.

**2. A code-side pre-filter is the most dangerous component in a pipeline**
The one thing that can drop a real signal with zero trace is a deterministic pre-filter. When tokens are cheap and the model has full context, inject everything and let the model judge - the filter's only value was keeping the prompt small, worthless at this volume.

Shipped to the box: prefetch.py `inbox` (body + X-GM-LABELS, no skip-list) + compose_brief triage rule; also carried the queued #2 fail-closed teacher fix over. eval.sh green (9/9); prod verified (box pulls 30 emails with bodies+flags, Gmail IMPORTANT captured).

## 2026-08-04 - grounded the brief's AI ADVANCEMENTS in real news (Tavily); killed the fabrication

The AI ADVANCEMENTS section had no news source - it was the model riffing from its weights.
So it drifted from specific named items (mid-July: MiniMax, Qwen, OpenAI Astra) to generic essays that echoed Daniel's own changelog and invented lab measurements ("third-party audits routinely measure above 40 points" - no source).
Fixed by making it a deterministic fetch, the same pattern as weather/inbox: code pulls the news, injects it as facts, the model only judges and cites.

### LEARNINGS TODAY - by subject (teach whichever is not yet on the taught list)

**1. Ground a generative section by FETCHING facts in code, not by asking the model to "use real news"**
`agents/brief/tools/prefetch.py` gained `ai_news`: a Tavily news search (official SDK, topic=news, one-week window, social/PR domains excluded) returning a compact sourced block, or `''` on any failure so the brief never breaks.
`compose_brief.py` injects it as a RECENT AI NEWS facts block, and the SYS rule now forces `ai_advancements` to cite ONLY from that block and never invent a statistic.
The model went from fabricating measurements to citing three real dated items (Shanghai AI Lab Shu'an, SageMaker Ground Truth Plus, Visa Agent Score) and dropping the junk (a stock page, a biopharma M&A) on its own.

**2. Analysis of 34 sent briefs: reliability is perfect, one section is silently broken**
31 consecutive days delivered at 07:30, no gaps; format locked ~07-15; the 07-24 "Friday 25 July" date-guess is gone (date is code-rendered now).
But ONE TECHNICAL THING has shown `[code not found]` every day since ~07-28 - a regression: real code was injected on 07-16 (`run_regression.py`) and 07-21 (`bedrock_adapter.py`), then broke when the top changelog entry became a conceptual one with no Twin code file, so the model invents a path and the deterministic extractor correctly 404s.
Fix is separate and pending: fail the teacher CLOSED to the real quiet-day item instead of shipping the 404 string.

Shipped: prefetch.py `ai_news` + compose_brief grounding; tavily-python in the box venv; eval.sh green (9/9). Tavily key in ~/.hermes/.env (rotate it - it touched a chat transcript).

## 2026-07-28 - practice day: deployed AWS's Strands+AgentCore eval sample end-to-end (not Twin code; learnings ledgered)

### LEARNINGS TODAY - by subject (teach whichever is not yet on the taught list)

**1. The offline/online eval cost asymmetry, measured: ~1000x**
Same eval framework, two runs: 85 offline tests with mock judges in 2.95s (~35ms/test) vs 18 deployed tests with a real agent + real LLM judges in 9m56s (~33s/test).
That three-orders-of-magnitude gap is WHY eval architecture is layered: deterministic gate on every change, judged suite at deploy time, production SAMPLED (theirs: 3%) - never fully scored.

**2. The onboarding path is the least-tested code in any repo**
Following AWS's own README on a fresh machine + fresh-to-the-service account hit 7 gaps: missing `botocore[crt]` for modern `aws login` creds; immutable ECR tag breaking re-push; API Gateway's ancient account-level CloudWatch-logs role; agent deps living only in the Docker image (local tests import-error); sample data never uploaded (ingestion silently fell back to 3 default vehicles with a green 200); the runtime ARN buried in a machine-named export; AgentCore metrics needing account-level Transaction Search the README never mentions.
Authors run the code hundreds of times and the first-hour path once; every difference between their world and yours surfaces as an undocumented error.
Corollary: reproducibility extends exactly as far as a drawn boundary (container, IaC, lockfile) - everything that broke was OUTSIDE the boundaries (local env, account history, auth style). Twin has the same disease; nobody has a first hour on it.

**3. "Is the system broken or is the ruler broken?" - twice in one day, in AWS's own code**
(a) Their deployment validator KeyError'd on its own wrong S3 response shape and reported it as an infrastructure failure - a blanket `except Exception` turning a validator bug into a false alarm (the exact silent-default anti-pattern the structured-output rule kills).
(b) Their CostEvaluator passed cases with "0 tokens, $0.00" on live LLM calls - green because the metadata was MISSING, not because cost was fine (a vacuous pass).
Both caught by reading primary evidence (the API response, the numbers) instead of trusting the checker.

**4. Smoke eval vs capability eval are different instruments**
The post-deploy smoke ran trivial no-tool cases on purpose: it checks alive/safe/fast/cheap (latency vs budget, cost vs cap, data freshness, guardrails), not intelligence.
Capability (real trajectories, judged output quality) lives in the deployed suite. Conflating them makes smoke slow and capability shallow.

**5. Dataset size follows the variable under test**
Their 4 dealer personas are ENOUGH - they test personalization behavior, not retrieval scale (53 vehicles, <1MB of vectors).
Twin needed 30 labeled questions before chunking arms separated. n is set by what varies, not by ambition.
Also: their stack is Twin's architecture in AWS clothing - EventBridge/Lambda ingestion = the pipeline, Titan 1024-dim = Cohere 1024-dim, LanceDB-files-on-S3 = sqlite-vec-file, contextualized descriptions = the contextual prefix, deterministic-veto gating (one safety violation fails the layer despite a high mean) = the 100% regression bar.

## 2026-07-27 - the eval flywheel synthesis: the grader ladder, datasets-are-code, UI-vs-CLI (reference diagram: docs/eval-flywheel.html)

### LEARNINGS TODAY - by subject (teach whichever is not yet on the taught list)

**1. The grader ladder** (frontier convergence, verified against RLVR/RLHF/CJE/Copilot papers)
Use the strongest signal the thing allows, best to worst: (1) CODE CHECK / RLVR - the answer is checkable or has ground truth, run on 100%; (2) BEHAVIORAL OUTCOME - did Daniel act / did it persist (GitHub Copilot: acceptance + code-persistence beat human ratings); (3) CALIBRATED LLM JUDGE - subjective residue only, binary + critique, trusted only when aligned (precision/recall vs Daniel's labels, never raw agreement); (4) THUMBS - weakest, gameable, sycophantic, never the anchor. The frontier moved AWAY from RLHF/thumbs (formally shown to amplify sycophancy) toward RLVR (verifiable) + calibrated reasoning-judges on binary principles. The unifying rule: the more you make the reward CHECKABLE instead of PREFERRED, the less it can be gamed. Twin's deterministic-by-default was engineering the whole system DOWN this ladder before we had the ladder.

**2. Datasets are code; label in the UI, build and measure in code** (the 0.37 -> 0.94 lesson)
The LangSmith UI is for humans-in-the-loop only: labeling in annotation queues, exploring traces, tuning a judge in the Evaluator Playground, watching dashboards. Everything mechanical is CODE (SDK): build datasets, run experiments, compute precision/recall, the ship gate, bulk ops. HARD RULE, learned the painful way: never build an eval dataset by scraping mixed runs through the UI - it gave the insight judge missing fields (it graded blind) and a bogus 0.37 alignment; rebuilt in code with ONE fixed schema (`inputs={ai_advancements}` / `outputs={insight_is_real}`) and it read the real 0.94 (precision 1.00, recall 0.92). Flow: label in UI -> rebuild as a clean coded dataset with a fixed schema -> eval + gate in code. Canonical golden set built: `brief-insight-golden` (17 clean examples).

**3. The domain-expert limit + the behavioral anchor**
Ground-truth-is-Daniel holds only where Daniel IS the expert. Scope `insight_is_real` to "useful / non-obvious TO ME" (he owns that), not "factually a real AI advance" (needs a source-check, not a judge - the insight judge grades feel, not truth; red-team confirmed it catches vague fakes but a detailed-but-false claim would slip). When quality is ambiguous even for experts (the "grey area"), anchor on a downstream BEHAVIORAL outcome - "did I follow up / fold it into a project" - and calibrate the cheap judge against that sparse-but-true signal (measure, never optimize the proxy directly - Goodhart).

## 2026-07-25 (ops) - summary-ingest dead-man fired (first live catch), token single-ownership enforced for real; shadow-judge paused
- THE ALARM WORKED: `twin-mind-summary-ingest-deadman` emailed Daniel within 12h of the ingester dying (the identical failure class previously rotted silently for 10 days). Root cause: refresh-token rotation AGAIN - copying one token file to the box created TWO consumers (hermes gateway auto-refreshing in memory + the ingester refreshing the file); the gateway consumed the rotating refresh token, the ingester's refresh got `invalid_refresh_token` (400), died before heartbeat. The single-ownership rule was written Thursday morning and violated by Thursday afternoon - by us.
- FIX (sole ownership, structurally this time): fresh `hermes mcp login granola` (Daniel) -> token installed as `granola-ingest.json` owned ONLY by the ingester; granola MCP REMOVED from the box gateway (`hermes mcp remove granola` + token cleanup + restart) - box chat now answers meeting questions from the ingested corpus (<=4h lag) instead of live MCP; Mac's token copy deleted after transfer (the family exists in exactly one place). Ingester refresh call fixed (urlencoded body + RFC-8707 `resource` param - diagnosed by reading the 400 error body: `invalid_refresh_token`, i.e. dead family, not malformed call; the call shape was fixed anyway). Verified: real run green, 12 meetings listed, heartbeat datapoint landed 21:32.
- SHADOW-JUDGE cron PAUSED (pause-not-delete): `judge_brief.py` POSTs scores to Langfuse without a traceId -> nightly "langfuse write failed" delivered to Telegram at 22:00. Its function is superseded by the LangSmith Layer-2 online evaluators (per the approved 3-layer design, which deletes the Langfuse mirror); resumable via `hermes cron resume shadow-judge`.

## 2026-07-25 - Twin's 3-layer eval system on LangSmith: tracing, anti-fabrication injection, online evaluators, annotation queue

### LEARNINGS TODAY - by subject (teach whichever is not yet on the taught list)

**1. Grader by failure mode, not by section** (the rule that resolves "which check goes where")
You do NOT choose "code check or LLM-judge" per section - you choose it per FAILURE MODE, and one section can hold several failure modes needing different graders. The AI-advancements section alone has three: "it's a headline not insight" (ambiguous -> LLM-judge `insight_is_real`), "it repeats a past day's topic" (checkable -> DETERMINISTIC dedup vs the covered list, never a judge), and "it states a false AI fact" (ungrounded generation, no source doc -> currently uncatchable; the only fix is to give the section a real source, then faithfulness becomes checkable). The rule: cheapest grader that fits - deterministic where there is ground truth or a checkable property, LLM-judge only for genuine ambiguity, human only to calibrate.

**2. Reference = ground truth = Daniel saying yes, and it is TWO independent axes**
Axis A: does a known-correct answer exist (reference) or not (reference-free). Axis B: is the check mechanical (code) or a judgment (LLM). They are independent - code-with-reference = triage exact-match vs the gold verdict; code-reference-free = sections_present; judge-reference-free = insight/coach quality; judge-with-reference = grade against a gold answer. Online production runs are ALWAYS reference-free (the run just happened, nobody wrote the gold yet); labeling in the annotation queue ADDS the reference and turns the run into an offline example - that is the flywheel's data half.

**3. Decompose the judge, never score "overall quality"; groundedness IS RAGAS faithfulness** (Hamel / RAGAS / deep-research papers, converged)
Grade SPECIFIC binary dimensions (groundedness, insight-is-real), never one "overall quality 1-5" - a single quality number is unactionable (nobody knows what to do with a 6), unalignable (broad criteria never converge with humans), and maximally biased (length/style). A rubric done right is a CHECKLIST of binary criteria, not a scale. Coach groundedness = RAGAS faithfulness (every claim supported by the source, no fabrication) with the day's facts as the source instead of retrieved chunks. An "overall/gestalt" judge is allowed as ONE extra dimension, calibrated separately, never a replacement for the specifics nor a rollup of them.

**4. Enforce facts by injection, not by prompting** (top rung of the reliability ladder, applied)
A fact the model should not reproduce (a code quote, a date) must be COMPUTED in code and injected, never asked for. The brief's technical section now returns `code_symbol` (a NAME) and `extract_symbol()` reads the real bytes from the file at render time - the model never sees or writes the code, so fabrication is impossible. The deterministic `code_symbol_real` check caught the live brief paraphrasing code into a fake "quote" before the fix. The model names WHAT, code supplies the bytes - same lesson as the date bug.

**5. You do not predict failure modes before production - you bootstrap, then usage teaches you** (the cold-start answer)
Enumerating every failure mode upfront is the documented mistake. Build cheap first: deterministic checks for properties you KNOW must hold (schema, format, dedup, quote-real - no failure data needed) + a judge for each KNOWN-LIKELY LLM weakness (fabrication -> groundedness, padding -> insight-vs-headline) + a small golden set from dogfooding and synthetic/adversarial generation. Then production reveals the rest and the flywheel folds them in. For the brief, Daniel is production-user-zero - every failure judged today (repetition, headlines, coach fabrication) came from USING it, not from a whiteboard.

**6. The judge's power is the few-shot examples, not the prompt** (why the zero-shot judges are only a v0)
A judge with a rubric but no examples is zero-shot - a hypothesis, not trustworthy for shipping. The labeled few-shot examples (Daniel's corrections) ARE the judge. LangSmith's "make corrections -> auto few-shot" wires this: a disagreement with the judge becomes a few-shot example in its prompt. Measure a judge by precision + recall on held-out labels, never raw agreement (imbalanced classes let a lazy "always pass" look 95% accurate).

### Shipped (3-layer eval for the brief on LangSmith EU; design docs/2026-07-24-langsmith-3-layer-evals-design.md, plan docs/2026-07-24-langsmith-3-layer-evals-plan.md)
- PHASE 0 tracing LIVE: `@traceable` on `compose_brief.compose` + `structured_call` (guarded optional import so a missing langsmith never crashes a live agent); `tracing_context` groups every brief into one LangSmith thread (`thread_id="brief"`, verified it propagates to the child structured_call). Box `.env` already had LANGSMITH_TRACING + EU endpoint + project twin-mind. Ship gate GREEN, deployed, trace verified.
- RUNG-3 ANTI-FABRICATION shipped: `TechnicalThing.code_quote` (model-written prose) -> `code_symbol` + `compose_with_real_code()` injects the verbatim block via `extract_symbol()`, one retry with the real symbol list, then a visible fallback. NEW `evals/brief_checks.py` (deterministic reference-free checks; TRACE_ONLY subset runs server-side), 15/15 tests, validated on a real brief (5/6 -> 6/6 after fix). Gate GREEN.
- PHASE 2 online layer LIVE in the LangSmith UI (Daniel drove it): `brief_structure` code evaluator (sections_present + no_em_dash, 100% of brief.compose runs, no credential) + `brief_insight` + `brief_coach_faithfulness` LLM-judges on Bedrock (eu.anthropic.claude-sonnet-4-5, temp 0, Converse; filter Name=brief.compose; few-shot corrections ON; extended-retention OFF). Server-side judges need a Bedrock credential in LangSmith - used a scoped `AWS_BEARER_TOKEN_BEDROCK` (Bedrock-invoke-only, revocable), NOT full IAM keys. TOKEN MUST BE ROTATED (it hit a chat). Box-side alternative built (`evals/brief_quality_judge.py`, instance-role Bedrock -> push feedback, zero creds in LangSmith) but Daniel chose the UI path.
- PHASE 3 flywheel STARTED: `brief-review` single-run annotation queue (default dataset morning-brief; Boolean rubric keys insight_is_real + coach_faithfulness matching the judges so labels align). Feedback tags set Boolean(0/1). Next: label existing briefs, accumulate daily, then align each judge in the Evaluator Playground (precision/recall on held-out).
- Watchdog role settled: LangSmith alerts use a 5-15 min window (built for streaming volume, not a once-a-day job), so liveness canNOT move to LangSmith; the watchdog shrinks to a daily heartbeat that queries the LangSmith API "did a brief.compose run since 07:00", while structural/quality checks live in the online evaluators.
- Cleanup: removed stale `pipeline/gold/` + __pycache__. NOT done: the one online alert (minor), the "verdicts" reply -> feedback wiring, prep + recap agents, token rotation. ~20 files uncommitted (Daniel's rule - not committed).

## 2026-07-24 (later) - structured-output retrofit #1: the ship gate's own graders

### LEARNINGS TODAY - by subject (teach whichever is not yet on the taught list)

**1. The data flywheel** (Daniel: "i finally got the flywheel"; the precise version per docs/2026-07-24-langsmith-3-layer-evals-design.md - being built NOW in the parallel session)
The flywheel is specifically the FAILURE loop, Layer 3 of the 3-layer eval architecture (Layer 1 offline gate, Layer 2 online monitoring, Layer 3 flywheel - all hanging off tracing):
a BAD live run (low online score, or Daniel replying "bad" to "Verdicts?") -> routed to an ANNOTATION QUEUE -> Daniel labels it with a written critique -> the labeled run lands in TWO places: the agent's GOLDEN DATASET (a permanent regression case the offline gate now tests) AND the judge's FEW-SHOT SET (the few-shot examples ARE the judge) -> the judge is RE-ALIGNED against Daniel's labels (precision + recall on held-out examples, never raw agreement).
Every fixed failure becomes a permanent test AND a sharper judge - that is the wheel.
Supporting method (Hamel Husain / Anthropic / OpenAI cookbook, converged): binary pass/fail + critique (never 1-5); one judge per failure mode; criteria come from GRADING REAL TRACES, not upfront rubrics; ERROR ANALYSIS (open-code ~50 failing traces -> cluster into a failure taxonomy -> count) decides which judge to build next.
Schneider Electric and Rippling run this exact shape in production on LangSmith. GEPA automates the optimize step later; the flywheel is why every verdict is captured and datasets compound.

**2. Structured outputs** (enforce the shape, never scrape it)
When an LLM must return structured data, FORCE it: expose the shape as a single tool (Pydantic schema = the tool's input schema), set toolChoice so the model cannot answer in prose, validate with Pydantic, feed validation errors back and retry (Instructor pattern), and RAISE if it never validates.
The anti-pattern it kills: prompt-for-JSON + re.search + `except: return False` - a parse miss silently becomes a wrong number in an eval or a default in prod, invisible until it corrupts a decision.
Mechanism lives in `shared/structured.py` (`structured_call`); reference pipeline `agents/brief/tools/compose_brief.py`; proven by A/B (brief: prompt-parse vs forced-tool-use; gate graders: behavioral equivalence + loud-failure mode).

**3. Ops: single-ownership + dead-man alarms**
OAuth refresh tokens ROTATE - two machines sharing one token family invalidate each other (the July Granola token deaths); every long-lived credential needs exactly one owner.
And every scheduled job needs a dead-man alarm: the transcript poller rotted silently for 10 days because it screamed by withholding a heartbeat nobody was watching.
- RETROFIT run_regression.py to the structured-output rule (the gate goes first - it guards everything else). TWO scraped LLM outputs converted: (a) the candidate decision itself - free text + `ACTIONABLE:` regex -> `decide()` returning an enforced `Decision{actionable, reasoning}` (temp 0.4 kept: trials exist to expose candidate variance); (b) `model_grader` - prompt-for-JSON + re.search + `except: return {"assertions": []}` silent default -> `structured_call` returning `AssertionVerdicts` (why-before-passed field order preserved), RAISES on invalid. `code_grader` now a typed comparison (still accepts the deterministic render text for the platform adapters - code-parsing-code, not LLM scraping). `eval_task.run_task` switched to `decide()`+`render_decision()` so the 4 platform adapters ride the same path.
- A/B'd on LangSmith (`evals/regression_grader_ab_langsmith.py`, dataset `regression-judge`: 3 gold items x 3 fresh decisions shared by both arms): judge-prompt-parse vs judge-structured both 9/9 on parse_ok / assertions_complete / agreement_with_code -> behavioral equivalence, no regression; the retrofit's value is the failure MODE (silent empty-default -> loud raise), which cannot show on rows that parse. Ship gate re-run on the new graders: GREEN (9/9).
- Next per Daniel's directive (one piece at a time): remaining silent judges (retrieval_eval llm_supported, generation_eval _judge, run_brief_bench judge, eval_task judge_one/judge_section, calibrate_judges), then background-prep + weekly-recap to the compose_brief pipeline shape. NEVER touch the live brief.

## 2026-07-24 - Granola ingestion rebuilt on the official MCP (summaries); token single-ownership; dead-man alarm
- DIAGNOSED the 10-day-silent Granola outage (full write-up + mermaid diagrams: docs/granola-ingestion-diagnosis.md): Granola auto-updated 7.394->7.441, deleted `storage.dek` and encrypted the whole local store -> the Mac poller's Path-2 decrypt chain died (break #2 in 2 months); no dead-man alarm existed on TranscriptPollerRan so it rotted silently. Separately, the box's granola MCP token expired ~Jul 16 with a dead refresh token -> headless OAuth crash-loop in every morning brief.
- ROOT CAUSE of the token deaths: Mac and box shared one OAuth client + refresh-token family (cloned at migration); refresh tokens rotate, so two consumers invalidate each other. RULE: the box is the SINGLE owner of the granola MCP token; never use granola from Mac-side Hermes.
- VERBATIM transcripts are now unreachable free: local store fully encrypted, official `get_meeting_transcript` is paid-tier-gated. Daniel's ruling (option 1): ingest official-MCP SUMMARIES - free, robust, survives app updates. Trade-off documented; paid tier reopens verbatim cleanly if ever wanted.
- SHIPPED: one-time `hermes mcp login granola` (Daniel, browser) -> token to box -> gateway restart (MCP test green, brief crash-loop gone). NEW `pipeline/ingest_meeting_summaries.py` (box-side, direct MCP JSON-RPC, self-refreshing token, baseline-marked 13 existing meetings, ingests only NEW; INCREMENTAL corpus.db+vectors.db inserts with the contextual prefix - never a rebuild, which would revert the windowed+ctx promotion). `summary-ingest.timer` every 4h. `twin-mind-summary-ingest-deadman` alarm (12h silence -> SNS). Old Mac launchd poller unloaded.
- WEEKLY-RECAP CRON WIRED (same day, ship gate green): `weekly-recap-nudge.timer` Fri 18:00 CEST + `weekly-recap-poll.timer` Fri 18:03-19:59/2min. Caught a real race at arming time: poll at 18:00 could beat the nudge, read LAST week's `nudge_ts`, see the 90-min cutoff "passed" and instantly send a week of Telegram as the reflection. Fixed twice over: poll starts 18:03 AND send_recap now refuses any nudge_ts older than 12h (smoke-verified: refuses with no/stale nudge). Stale Jul-18 test state cleared. First automatic run: tonight.
- REMAINING from the 3-day bot review: brief skill-trust + cron-approval errors (Daniel editing SKILL.md/prefetch.py himself).

## 2026-07-21 - retrieval eval: windowed + contextual embedding win, reranking declined (measured)
- BUILT the RETRIEVAL eval (`evals/retrieval_eval.py` + `evals/retrieval_braintrust.py`): context recall@k on `corpus-qa`, vector lane only (isolates the knob under test), two hit definitions - deterministic `source_recall@k` (home meeting in top-k, via a new `home` field) + LLM context-recall cross-check. Two Braintrust experiments per config; a config ladder (`CONFIGS`) where each rung = one cleanly-named experiment.
- GREW `corpus-qa` 24 -> 54 rows (30 home-labeled, all conversational/transcripts) by synthetic-from-chunk drafting + Daniel's keep/fix/drop. The dataset was the limiting instrument: 7 conv questions couldn't separate the arms; 30 could. (The other 24 rows lack `home`, so `source_recall` scores the 30-row conversational subset.)
- ABLATION (coordinate-ascent, one knob at a time, measured by `source_recall@10` on 30 rows):
  - windowed chunking beats per-turn: 86.7% (and 2x faster, 12x fewer conv vectors, 0 regressions).
  - + CONTEXTUAL EMBEDDING (prepend `[meeting . date]` to each chunk before embedding; `pipeline/add_context.py`): 93.3% (+6.7, 0 regressions) - the real win. Anthropic's Contextual Retrieval, deterministic version; the meeting stem carries the participant names that speaker-anonymized text ("them:") drops.
  - + RERANKING (Bedrock `amazon.rerank-v1:0`, eu-central-1/Frankfurt = in-EU; cohere.rerank needs a Marketplace subscription so switched to first-party): flat at @10, +3.3 at @5 only (+1 question). DECLINED - marginal, not worth the cross-region hop + latency. Anthropic's biggest lever gave us ~nothing because contextual already saturated recall. Measure-before-adopt, again.
- INFRA: parametrized `embed_corpus.py` (`--inputs/--out/--maxch`, defaults unchanged - production embed untouched); added `bedrock:Rerank` to the `twin-mind-role` policy (Daniel applied it - IAM elevation stays human-approved).
- GENERATION eval built (`evals/generation_eval.py`): faithfulness 98% + answer_correctness 59% on 54 rows = the generator is honest (barely hallucinates); correctness is capped by RETRIEVAL/coverage, not the writer. The split is diagnostic - a blended "answer quality" score would wrongly blame generation.
- PROMOTED to production: hybrid re-verify passed (per-turn hybrid 80% -> windowed+ctx hybrid 93.3% @10, +13.3 on the 30-row ruler), so rebuilt BOTH production indexes (`vectors.db` + `corpus.db`) from windowed+contextual (`build_index.py` parametrized to match `embed_corpus.py`; new `evals/hybrid_check.py` is the promotion gate), backed up the per-turn originals (`.per-turn-bak`), swapped, smoke-tested (hybrid returns the right sources), ship gate GREEN (regression 3/3). Twin's live retriever is now windowed+contextual on BOTH lanes; brief/Q&A benefit immediately (corpus-search reads fresh per query, no restart). Reversible via the backups. Reranking stays declined.
- REMAINING (documented follow-ups): gmail still per-record + quote-unstripped (design-doc TODO); the ruler is transcript-only (gmail/imessage/gchat retrieval unmeasured); answer_correctness 59% is a retrieval-COVERAGE gap, not a generation one.

## 2026-07-17 - caching win confirmed in prod, agents rundown, weekly-recap agent (one-shot)
- CACHING PAYOFF confirmed in PRODUCTION via CloudWatch (yesterday's `cachePoint` fix went live on the gateway restart): today's brief window shows `CacheReadInputTokenCount` 2,463,513 (read at ~1/10 rate), `CacheWriteInputTokenCount` 87,004, and only 67 full-price input tokens. Off yesterday (0 cache-reads) -> ~90% of input now served from cache. Confirms probe -> patch -> restart -> prod end to end; AWS-side evidence, independent of the framework (which doesn't record cache tokens). Lesson banked: measure, don't assume - the 4-line probe found a silent 10x cost leak the doc swore was fixed.
- WEEKLY-RECAP AGENT specced + started. Brainstormed scope/goals/architecture (mirror the brief: deterministic prefetch + LLM compose + grounding rule; Friday cadence). /stepback caught it was over-engineered (cron + Telegram nudge + UNBUILT reply-capture + watchdog for a weekly self-email) and that reply-capture is vapor (background-prep's goal-ask writes nothing back; `feedback.jsonl` has no code writer). PIVOTED to a one-shot: `agents/weekly-recap/tools/recap.py` - deterministic `changelog_week()` (verbatim, TZ Europe/Luxembourg) + Sonnet compose (grounded, date injected, temp 0) -> dry-run `.txt`, reviewed before send. First dry-run caught 3 real grounding bugs (guessed the date, fabricated a count 27-vs-26, truncated and dropped section 3) - all fixed. Promote to a real cron agent later, with tonight's reviewed output as the first fixture. Lesson: dry-run-and-review before an unattended live send is the whole point; a weekly agent hides a silent bug for a week.
- AGENTS RUNDOWN mapped: `chat` (interactive twin) + `brief` + `background-prep`, one ingest pipeline (Granola + corpus), one SOUL, one eval gate.

## 2026-07-16 - brief judge split into 5 per-job evaluators
- FINDING: the one blended section judge was really 4-5 evaluators sharing a prompt + scorecard. The 76% "agreement" was the mean of {triage 83, ai_news 92, teacher 33, coach 91, overall 50} - it hid that teacher is badly miscalibrated. `expected` meaning changed per hidden `section` field = several evals masquerading as one.
- SPLIT: one (dataset, judge, agreement-target) per section. `evals/compare/eval_task.py` adds SECTION_JUDGES (criteria/few-shot lifted VERBATIM from calibrate_judges.py), `section_rows()`, `dataset_rows()`; new `evals/calibrate_sections.py` reports 5 numbers each with its own target. overall kept HOLISTIC - a measured deterministic rollup mismatched Daniel's gestalt (50%->25%).
- VALIDATED (Sonnet temp 0 vs labels): triage 83, ai_news 100, teacher 33, coach 91, overall 67 (total 82). Faithful decomposition - no section regressed; the two gestalt judges improved once focused. teacher (33%) + overall (67%) are now first-class numbers below target = next fix targets. triage misses are staleness (deterministic layer's job; judge told to ignore).
- VISIBILITY: 5 `brief-<section>-verdicts` datasets mirrored to all 4 platforms (Langfuse idempotent; Braintrust/LangSmith/Arize section-only). Slices share the one source file (brief-section-verdicts), filtered by section - no duplicate files to drift.
- Eval gate GREEN (additive eval tooling; regression 3/3x3). Production brief judge UNCHANGED - a per-section swap is a separate ship-gated proposal.
- Prior in-session: rubric experiment (analytic binary-checks) measured WORSE (76->70, rollup mismatch) -> not adopted, holistic kept. CORRECTION: Bedrock Converse path has NO prompt caching today (build_converse_kwargs emits no cachePoint; logs show no cache-read) - the 2026-07-03 "caching works" note is stale post-Converse-migration. Live probe confirmed (0 cache-reads on the agent's shape; 4.5-7.2k read at ~1/10 rate with a cachePoint).
- CACHING FIXED + verified: patched `build_converse_kwargs` (Hermes agent/bedrock_adapter.py) to append a `cachePoint` to the system block when the system prefix is large (>6000 chars). Verified big-system caches / small-system skips / both return valid output. Backup at `bedrock_adapter.py.bak-cachepoint`. Local framework patch (re-apply after Hermes updates); activates on next gateway restart; system-prefix only (message-level caching is a follow-up).
- TEACHER judge: investigated the 33%. Rubric tuning whack-a-moled 33->67->0 on n=3 -> STOPPED (the defects are not the prompt's to fix). Diagnosis from Daniel's own labels: bad = missing quiz answer (ALREADY fixed - skill requires it + `brief_check.py` flags a missing `Answer:`) + wrong/stale item number. SHIPPED the source-injected fix: `prefetch.technical_item()` counts the digest-queue (day-of-year mod 14 - the hidden `3b` made the count stale) and injects the exact item; the skill fallback now reads it instead of doing the mod. Gate GREEN, active next brief. Backups `*.bak-teacherfix`. "More labels" is data-limited (only 3 teacher sections exist) -> going-forward habit, not a today task.
- INTERVIEW PREP: eval-fluency prep sheet (7 concepts + "why not the other way" lines + judge-bias pushback + proof numbers) saved to `~/Desktop/Career/Langchain/prep/eval-fluency-prep.md`; pointer added to the langchain interview memory. Whole session done IN the platforms (Braintrust hands-on) per the "work in the platform, not the terminal" lesson.

## 2026-07-15 (later) - four-platform eval bake-off + judge few-shot + dataset renames + Langfuse mirror
- JUDGE few-shot + reason-first across all 4 judges; calibration eval caught a bundled regression
  (ai_news cross-brief memory deletion, 80->66), restored -> ai_news 100%; ship gate held 3/3.
- DATASETS renamed to plain words (gold/labels/archive/fixtures -> answers/verdicts/sent/inputs);
  all code refs + box files updated, gate green.
- LANGFUSE: verified healthy (earlier "broken" was a wrong-key-name probe + stale OTel warning);
  evals/push_to_langfuse.py mirrors the 5 datasets into Langfuse Datasets; rule added to CLAUDE.md
  (everything must also reach Langfuse for Daniel's visibility).
- FOUR-PLATFORM BAKE-OFF (Daniel's ask): evals/compare/ - one shared inbox-decision eval, four thin
  adapters. All live: Langfuse (datasets), Braintrust (EU, datasets+experiment, Eval() one-call, 100%),
  Arize (EU eu-west-1a, datasets+experiment via ax CLI - US default 401s EU keys, the gotcha),
  LangSmith (EU, datasets+experiment via evaluate(), project twin-mind; key recovered from Daniel's
  on-disk demo .env). Real-data-to-all-4 = deliberate override of EU-residency ground truth (derived
  data only; raw corpus stays local). Scorecard artifact published. FINDING: Langfuse is the only one
  of the four NOT on its EU host (cloud.langfuse.com vs eu.cloud.langfuse.com) - flagged.
- Setup-friction ranking (firsthand): Braintrust smoothest, LangSmith clean, Langfuse env/id quirks,
  Arize most friction (CLI-only datasets + region 401 + manual experiments). All ingest OTel = no lock-in.

## 2026-07-14 (later) - granola transcript ingest BUILT, gate-green
- pipeline/fetch_granola.py BUILT: Mac-side 15-min poller, the post-call mirror of background-prep.
  Path-2 auth chain lifted verbatim from the proven granola_path2_decrypt.py (Keychain -> storage.dek
  -> DEK -> supabase.json.enc -> live Bearer). Lists /v2/get-documents, and for any NEW meeting whose
  transcript is final saves the verbatim Me:/Them: transcript to raw/transcripts-inbox/, then normalize
  + build_index inline. Deterministic, no LLM, no secrets ever printed or written.
- Scope enforced (Daniel's ruling): first run BASELINES every current meeting (no file, never
  backfilled); only meetings appearing after baseline are ingested. State: ~/.hermes/state/transcript-state.json
  (seen doc ids + updated-timestamps + written filename). Saved doc whose updated-timestamp advances is
  re-fetched and overwrites the same file; unchanged docs never re-fetched.
- Speaker map: source microphone -> Me, everything else -> Them (strict, all the normalizer reads today).
  Finality gate: segments exist AND tail is_final; a still-transcribing meeting stays pending and is
  re-checked next poll (no half-written file). Any fetch/parse failure is counted AND printed, never hidden.
- Failure doctrine: decrypt/Keychain failure SCREAMS (prints loud, skips heartbeat so the dead-man fires,
  exits 1); a 401 is the soft "app not running" state (retry next poll). Heartbeat is two-way: local
  timestamp file (authoritative Mac-side, weekly-review checks staleness) + best-effort CloudWatch
  TranscriptPollerRan. Reindex runs under a non-blocking flock so it never overlaps a manual corpus refresh.
- normalize_transcripts.py: one-line SOURCES add (raw/transcripts-inbox/*.md) - wires in the inbox AND
  finally the hand-pasted tiffany file (14 turns). Verified without mutating the real corpus.
- 33 GRANOLA-INGEST FIXTURES born into the gate (evals/test_granola_fetch.py, wired into eval.sh next to
  test_prep_scan.py): baseline scope + freeze/no-backfill, idempotence, update re-fetch (same file reused),
  finality gating, speaker mapping, parse-failure honesty, failed-doc retry. Injected at the fetch boundary
  so no test touches network or Keychain. Gate GREEN (26 prep + 33 granola fixtures + 9/9 regression).
- launchd LaunchAgent staged: infra/com.twinmind.granola-transcript-poller.plist (15-min, RunAtLoad,
  logs to ~/.hermes/logs/granola-poller.{out,err}.log). NOT loaded - install one-liner handed to Daniel.
- DEVIATION from spec: reindex runs normalize + build_index (FTS, free, local) inline, but NOT the Bedrock
  embed step - it rebuilds the whole vectors.db over the network and costs money every poll (a 15-min-poller
  cost trap that also couples ingestion to AWS). New meetings are keyword-searchable within minutes; vectors
  catch up on the existing weekly Mac->box refresh. Incremental append-embed noted as the future optimization.

## 2026-07-14 (late night) - background-prep BUILT, gate-green, deploy staged
- AGENT #2 BUILT per spec v2: agents/background-prep/{SKILL.md (dossier contract, cite-or-refuse,
  privacy query rule + query log), JOB.md, tools/scan_meetings.py (15-min no-agent poller: ICS
  physics, circle/video-link scope filter, 75-min idempotent catch-up, 20-min claim lease, 21:00
  goal-ask, PrepPollerRan heartbeat, shadow-flag file)}. personal_circle.txt seeded (manual on
  purpose: contacts.jsonl has phones, not relationship-tagged emails).
- Spec deviation recorded in JOB.md: no-agent poller can't invoke the model, so it schedules a
  one-shot Sonnet cron; the spec's lost-prep objection is answered by the lease (stale claim
  expires -> retry). Nothing can be silently dropped.
- 15 CALENDAR-PHYSICS FIXTURES born into the gate (evals/test_prep_scan.py, wired into eval.sh):
  Z-vs-TZID same instant, all-day/cancelled excluded, circle filter, video-link rule, folded
  ATTENDEE, lease expiry, delivered idempotence, recurring keyed apart. All green first run.
- SKILL-GUARD FIX along the way: gateway re-materializes bundled skill dirs on restart
  (.bundled_manifest, reappeared 13:25) - "symlinks only" unenforceable; guard now allows
  manifest-listed dirs only. Would have false-alarmed the 07:50 watchdog on day one of v3.
- Gate GREEN (fixtures + 9/9 regression). Deploy payload staged; box push HELD pending Daniel's
  answer on the Fargate question (asked mid-deploy). Shadow week starts at deploy.
- Agent card artifact published (scope/access/middleware/model/evals/det-vs-agentic/stack fit).
- PRE-PROD EVAL built (Daniel's ask) and it PAID immediately: evals/run_prep_bench.py --scope
  replays the filter over the REAL feed (27 events/30d). Caught 3 prod bugs before prod:
  (1) recruiter as ORGANIZER-only never counted (Growth Protocol interview would have had NO
  prep), (2) Meet link lives in X-GOOGLE-CONFERENCE/LOCATION not DESCRIPTION, (3) mirrored
  invites (same start+link) would double-dossier. All fixed + 6 new fixtures; gate 21/21 green.
  --pick 8 selects past real meetings for the [BENCH] dossier run through the real harness;
  Daniel's verdicts on those = prep-labels.jsonl golden set, born before launch.
- DANIEL'S GO + scope ruling ("any meeting is important" - err inclusive, circle starts empty,
  recorded in JOB.md). DEPLOYED: files+symlink+shadow flag+watchdog fix on the box, prep-poller
  cron */15 live (first tick 17:15), PrepPollerRan seeded + 3h dead-man alarm (in
  recreate-monitoring.sh), 8 [BENCH] one-shots fired 17:10-17:38 on real past meetings
  (Chainfill, LangChain, Nik, Roxi, Postral, Spiros, 2x AWS interviews). Cron-create quoting
  lesson: positional prompt dies in nested bash -lc; pass args directly to sudo.
  Tonight 18:45: first organic shadow prep (Sam/Postral 20:00).
- BENCH VERDICTS 1-5 (Daniel, live): 1-3 good (Chainfill/LangChain/take-home; LangChain dossier
  reconstructed the full 4-round pipeline + rejection reason from Granola). Two findings became
  fixes, both gate-green (26/26) + deployed:
  (1) NIK DOSSIER RENDERED AS BLUE HTML - root cause: gateway delivers final Telegram msg as
  MarkdownV2 (cli-config.yaml.example:634); brief was immune only because it is EMAIL. Dossier had
  no plain-text contract so a run formed a valid MarkdownV2 entity. Fix: hard PLAIN-TEXT rule in
  SKILL (no markup, no < >, rewrite 'X <-> Y' to 'X / Y', no em dash, straight quotes).
  (2) INTERVIEW GOAL 'impossible to infer' cold - added deterministic is_interview() (title words
  + ATS/recruiter domains) -> passes 'MEETING TYPE: interview' so the candidate frame + fixed goal
  hold even with zero corpus history. 5 fixtures. Roxi dossier SELF-FLAGGED personal (spotted
  'Ma Corla' Spanish endearments) - scope self-correction working; circle candidate.
  prep-labels.jsonl now 6 rows (the golden set, growing from live verdicts).

## 2026-07-14 (night) - v3 shipped, judge calibrated, bake-off run, second agent specced
- BRIEF v3 LIVE for tomorrow 07:30: designed WITH Daniel (act-fast core: one-liners no drafts;
  weather; conversation-driven teacher w/ answers; dedupe enforced; open-loops dropped), built as
  deterministic prefetch (state-flagged inbox, noise tier, Open-Meteo) + prose-only agent + v3
  watchdog (subject-date, Answer-line, weather, dedupe checks). Cron carries the script stage.
- REPO RESTRUCTURED agent-shaped: agents/{brief,chat}, shared/, evals/, pipeline/. Leanness law in
  CLAUDE.md. Box skills: 4 governed only (18 bundled archived). Gate stayed green through the move.
- JUDGE CALIBRATED: 64% -> 80% in one rubric iteration vs Daniel-endorsed labels (62); remaining
  disagreements = instrument-scope (staleness->regression suite, answer-line->watchdog). Judge
  caught one wrong label ([7] Dan Luu repeat). calibrate_judges.py is the standing harness.
- MODEL BAKE-OFF (regression eliminator): Sonnet 9/9, Haiku 9/9, gpt-oss-20b 9/9 (!), 120b 8/9 DQ,
  Nova-2-Lite 0/9 (floor = format compliance). Haiku 3-day brief trial starts Jul 16 (one variable
  at a time; verdicts referee). OPEN: 20b prose benchmark failed 3x (args/env/HTML error) - rerun
  FOREGROUND with full stderr before judging its prose; does not block Haiku trial.
- SECOND AGENT SPECCED: agents/background-prep (dossiers ~1h before professional calls).
  Brainstormed with Daniel (Telegram T-60, mechanical scope filter, infer-goal-ask-when-thin,
  half-page). Hostile stepback adopted: idempotent catch-up poller (no one-shot machinery),
  attendee-not-organizer heuristic, personal-circle day one, outbound-query privacy rule + log,
  calendar-physics fixtures in the gate, shadow week, Sonnet at launch. Gate zero PASSED (ICS
  carries ATTENDEE/ORGANIZER/DESCRIPTION). Principle recorded: every agent is tested on ITS OWN
  job before model swaps.
- QA-gold minted (24 items, Daniel's prose-style labels; AM = TAX dept agents, internship ends
  Sep 9 - major fact corrections propagated to wiki).

## 2026-07-14 (evening) - stepback #6: refocus, green gate, freeze list
- RED GATE resolved per cold ruling: regression pass = code grader AND every assertion; the judge's
  holistic "overall" bit DELETED (a vibe layered on a deterministic pass; flicker was grader skew
  from the jargon-rename, not a regression). 9/9 green; inbox-decisions renames landed; deployed.
- Collaboration rules adopted (in CLAUDE.md): one-consolidated-ask when human input blocks >24h;
  Daniel timeboxes label sessions like meetings.
- CRITICAL PATH (5 steps): [1] gate green DONE -> [2] Daniel's 35-min label session -> [3] calibrate
  shadow judges vs labels -> [4] five-model bake-off -> [5] Session B brief workflow-ification.
- FROZEN: Session C hardening (except Daniel's 10-min interactive credential run) until bake-off
  ships; cross-run memory beyond digest-covered until Session B; teacher-gold until a real drill
  session produces material; fine-tune until 50+ labels AND post-Aug 6.
- DROPPED: further naming passes until September; datasets/-move + folder-rename cosmetics.

## 2026-07-13 - the twin's secret diary
- INCIDENT: brief showed Sam/Postral meeting at 17:00; real time 19:00. Root cause: calendar_read
  stripped ICS timezones (the Z suffix) - not a hallucination; the model faithfully relayed bad tool
  data and added an unwarranted "CEST" label. Fixed (Z + TZID -> local), proven against the live event.
- DISCOVERY via trace diagnosis: the twin maintained a private self-authored skill
  ("morning-brief-infra-notes"), patched it 3x this morning, and even ATTEMPTED to patch the governed
  morning-brief skill (blocked by a profile quirk, not obedience). Framework's skill_manage guidance
  conflicted with our SOUL rule.
- THE TWIST: the diary was ~85% verified gold - including a REAL bug in send_email.py (missing
  datetime import; the cursor NEVER wrote; the twin manually worked around it daily since Jul 9
  without telling us) and Tirith scanner patterns explaining past format constraints. Also contained
  confident false entries (--today flag "confirmed working" - flag doesn't exist).
- RESOLUTION: bug fixed (twin credited), diary salvaged into governed skills/morning-brief/OPERATIONS.md
  (corrected), rogue skill deleted, SOUL loophole closed (no skill_manage; report bugs same day, never
  silently work around), Sunday review now surfaces undocumented workarounds. Gate green; all deployed.
- Feedback row logged (calendar tz). Langfuse thread view = Sessions tab (answered).

## 2026-07-12 - the loop learns to listen
- SHIPPED through the gate (9/9 green): brief format contract + fact-density pin, feedback capture (Daniel's daily verdicts -> datasets/feedback.jsonl), SOUL explaining rule, audience-retrieval router (drift found by Daniel's "where in the code?" - verdict 07-03, deployed 07-12, receipts: family content 0.37->0.07 under hybrid retrieval).
- Renames per new global naming rule: run_triage->run_regression, run_baseline->run_benchmark, TRIAGE_SYS->INBOX_DECISION_RULES, scorecard-pairs->gold-candidates-pool; stale artifacts archived.
- Doctrine adopted: docs/eval-doctrine.md - two LangChain online-eval articles translated to n=1 (deterministic checks on everything, judges calibrated against Daniel, verdicts->dataset within a day, weekly review queue). All four of Daniel's proposed evals (coach/teacher/email/retrieval) formally planned.
- Artifacts: agent-memory whiteboard + evals whiteboard (claude.ai/code).
- OPEN: brief_check.py (07:50 outcome+format verifier), datasets/ move, ~/twin-mind folder rename (Daniel's go), hardening session (automation credential first), judges after ~20 verdicts.

## 2026-07-08 - Session A complete: the evals RUN
- Deployed to box: SOUL time rule, inbox cursor + coverage contract, digest section ("one technical thing" daily, interview-gap queue leads), 8 learning-wiki files. Gateway restarted.
- FIRST regression suite run: tools/run_triage.py (3 tasks x 3 trials, code+judge graders, tracked metrics) -> 9/9 PASS. Baseline established.
- evals/eval.sh = the ship gate; CLAUDE.md rule: no skill/prompt/model change ships without it green.
- Research trio audited (Anthropic evals + BEA, OpenAI guide, 12-Factor): ~85% aligned; fix plan at docs/plans/2026-07-08-compliance-fix-plan.md (Session B: brief workflow-ification; Session C: hardening).
- Interview retrace: verbatim misses filed + Tiffany debrief transcript in corpus; Robert window ~Aug 6 (Daniel's own request, confirmed by mailbox read); triage-03 minted from the brief's missed-reply error.

## 2026-07-04 - first production incident, resolved same day
- INCIDENT: first unattended 7:30 brief failed to email (silently). Root cause: Docker terminal sandbox starved the agent's hands (.env/tools/venv absent in container). The twin diagnosed its own confinement, composed a degraded-but-smart brief from Granola+memory, delivered via Telegram, and stated the cause. Latest-state rules visibly applied ("state ambiguous - present as question").
- FIX 1: box terminal.backend -> local (documented trade-off: single-purpose zero-inbound box; approvals+SOUL rules remain; "Docker with proper mounts" backlogged).
- FIX 2: inbox_read --hours was date-granular (IMAP SINCE) -> real hour cutoff added. CORRECTION: yesterday's "test email arrived" was a false positive from this bug; box email delivery had never actually worked until today.
- FIX 3: heartbeat via aws CLI subprocess (system python3 lacked boto3; failure was swallowed as designed).
- VERIFIED end-to-end as cron runs it: email delivered + BriefSent metric = 1.0 in CloudWatch.
- LESSON BANKED: detection lag (24h alarm) too slow - tighter schedule-aware check backlogged; verification tools must be tested for lying before being trusted.
- Also: AWS login session expiry keeps severing the admin tunnel (3rd time) - scoped automation credential for the Mac->box sync queued in hardening batch.

## 2026-07-03 (evening session)
- MILESTONE COMPLETE: morning brief cron scheduled (7:30 daily, box) + scheduled path proven E2E (test brief delivered) + dead-man's switch armed (code-level BriefSent heartbeat in send_email.py, 24h CloudWatch alarm -> SNS; pending Daniel's subscription confirm).
- cron_mode: deny confirmed NOT to block the brief's send path.
- Prompt caching ground truth CORRECTED: measured working on Bedrock (~83-99k cache-read tokens/turn, ~1/10 rate); compaction policy queued for the fattening Telegram session.
- Papers reviewed (middle-depth): MemGPT (validates stack; steal memory-pressure saves), PersonaTree (wiki-v3 blueprint: patterns layer + per-claim confidence + depth-conditioned retrieval).
- New skill: research-papers (Semantic Scholar REST via curl, keyless). Deployed to box.
- Box fixes: langfuse SDK installed (traces verified from box), sqlite-vec installed (hybrid verified server-side), pairing re-approved, SOUL knows its runtime.
- Corrections banked as regression data: twin-triage-v1 (2 items: source-coverage, recency-resolution) + skill rules.
- OPEN (tomorrow's hardening batch): secrets -> SSM Parameter Store, compromise runbook, pinned dependency manifest (4 missing-dep strikes), weekly Mac->box corpus refresh, nightly ~/.hermes state backup, ephemeral tool-status UX (grounding needed), invariant eval suite, correction auto-capture.

## 2026-07-03
- MIGRATED: twin now 24/7 on EC2 (eu-west-1, zero-inbound, SSM-only, Docker sandbox). Mac = corpus factory. Cutover clean (single-owner order).
- Fixed on box: messaging extra, sqlite-vec (hybrid verified server-side).
- Security: untrusted-content rules added to SOUL (injection); twin forbidden from self-editing skills.
- First live morning brief sent + self-verified; 2 staleness errors -> twin-triage-v1 regression dataset + 2 skill rules (latest-state check, Granola source coverage).
- Senses: Telegram paired (Daniel only), local Whisper voice, IMAP inbox reader (PEEK), ICS calendar reader (+recurrence), Notion+Granola MCP, web pinned (Tavily search / Firecrawl extract).
- Corrections banked: LangChain rejected (door open ~Sep), thesis defense reset from Jul 7.
- Audit (am): repo = single source of truth (symlinks), launchd service, hybrid default deployed, judge temp 0, debris deleted.
- Stepback #4 verdict adopted: milestone = "loop runs unattended every morning and screams when it fails". OPEN: 7:30 cron + E2E scheduled test + dead-man's switch; secrets->Parameter Store + runbook; weekly corpus refresh.

## 2026-07-02
- Corpus complete: 34,713 records / 6 sources (Gmail denoised 58.9k->5.4k); wiki v2 (2017-2026).
- Gold set: 32 pairs, audience-sliced; judge (content/fidelity/aspiration); 6 experiment runs -> hybrid default for Q&A, audience-conditional drafting retrieval, tuning stopped at benchmark resolution.
- Embeddings: 25,473 vectors (Cohere multilingual v3, sqlite-vec, ~$0.40).
- Langfuse tracing live + score configs; cost measured ~$0.007/turn (caching verified).
- AWS: daniel-admin (root retired), budget alert (credits excluded), box launched then stopped.

## 2026-07-01 and earlier (Jun 30)
- Scope + rules locked (eval-first, simplest/deterministic/auditable, two-tier corpus privacy).
- Machine indexed (161k files); 20GB disk freed; iMessage 20,583 + transcripts 6,558 turns ingested; wiki v1; corpus local-only git with push-block.
- Hermes chosen + installed on Mac; Bedrock EU; first corpus-grounded answer (Max Hammer, 28 tool calls).
