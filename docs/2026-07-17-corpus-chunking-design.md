# Corpus chunking redesign - conversational data

Date: 2026-07-17.
Trigger: the incremental-embed eval showed a Granola meeting was embedded but not semantically retrievable.
Root cause turned out to be systemic: the corpus is chunked one message / one turn per vector, which is wrong for conversational data.

## The problem, measured

One normalized record = one embedded vector. Current sizes:

| Source | Vectors | Median chars | Unit | Verdict |
|---|---|---|---|---|
| gchat | 1,563 | 7 | one message | noise |
| imessage | 20,583 | 19 | one message | noise |
| transcripts | 6,730 | 44 | one turn | noise |
| gmail | 5,421 | 929 (truncated at 1500) | one whole email | too coarse + truncated |

~28k of ~34k vectors are conversational micro-chunks like `"ok"`, `"lol"`, `"No. You're good."`.
You cannot semantically retrieve a topic out of a 19-character fragment, and the meeting's real content is scattered across dozens of tiny turns, none of which alone matches a topical query.
Emails are the opposite failure: one giant vector per email, silently truncated at 1500 chars in `embed_corpus.py`.

## What the research says (convergent across Cohere's transcript cookbook, conversational-RAG guides, the 2026 chunk-sizing catalog, and memory papers)

1. Never index a message/turn individually - short out-of-context messages are meaningless and add noise. This is the #1 named failure mode, and it is exactly ours.
2. Group into windows by three signals: same thread + time proximity (2-5 min gap) + speaker turns. Each chunk is a coherent slice of conversation.
3. Size ~300-500 tokens with 20-30% overlap for conversational transcripts (highest overlap of any content type - topics shift fast). Cohere embed-v3 caps at 512 tokens, so stay under that.
4. Keep the speaker in every chunk (`Me:` / `Them:`) - needed for "what did X say" retrieval and for trust.
5. Metadata matters as much as size: thread id, speakers, timestamp, order - so context can be reconstructed after retrieval.
6. Email: strip the quoted history first (kills the biggest source of duplicate retrieval), then chunk the body ~500 tokens - do not truncate.
7. Long threads get two layers: a per-meeting/thread summary vector for broad queries, plus the windowed chunks for specifics. Retrieve small, return parent.
8. At retrieval: rerank + fetch adjacent chunks + reorder by timestamp. We already have hybrid (FTS + vector + RRF); a reranker is the next add.

## The plan for Twin Mind

| Source | New chunking |
|---|---|
| imessage / gchat | window consecutive msgs: same chat + <=5 min gap, speaker-labeled, ~400 tokens, 25% overlap; drop <20-char standalone chunks from the index (keep raw) |
| transcripts | window turns to ~400 tokens, 25% overlap, speaker labels kept; add a per-meeting summary vector (two-layer) |
| gmail | strip quotes -> chunk body ~500 tokens; remove the 1500 truncation |
| all | keep thread/speaker/timestamp metadata; add a reranker at query time |

The incremental embedder (`embed_corpus.py --only`, built 2026-07-17) makes re-embedding after a re-chunk cheap.

## Prove it before adopting (the eval) - retrieval and generation are SEPARATE

Do not adopt on faith - that is the session's own rule.
And do not blend retrieval with generation - that is the same blended-metric anti-pattern we split the brief judge for.
This maps exactly to RAGAS (the reference RAG-eval framework, arXiv 2309.15217), which does component-wise evaluation:

| Eval | RAGAS metric | Isolates | Needs |
|---|---|---|---|
| Retrieval (this chunking decision) | context_recall (+ context_precision) | retriever + chunking | question, retrieved_contexts, reference |
| Generation (separate follow-up) | faithfulness/groundedness + answer_correctness | the generator LLM | + response |

The data columns prove the split is real: a retrieval number needs `retrieved_contexts`; a clean one is impossible from an end-to-end run.
We are stronger than default RAGAS here: `corpus-qa` has hand-corrected GOLD answers, so we run reference-BASED metrics, not RAGAS's reference-free proxies.

For the chunking decision, build the RETRIEVAL eval ONLY: for each `corpus-qa` question, retrieve top-k against per-turn vs windowed vectors; a hit = the answer's content appears in top-k (context recall@k). Compare per-turn vs windowed.
The generation eval (faithfulness + answer_correctness) is a separate experiment on the same dataset, run when answer quality is the question, not chunking.
Run both in Braintrust as two experiments (one-eval-per-job).

## Status - RESOLVED 2026-07-21

Built and measured. Ablation by `source_recall@10` on 30 home-labeled conversational questions
(`corpus-qa` grown 24 -> 54), one knob at a time (coordinate ascent):

| Config | source_recall@10 | Decision |
|---|---|---|
| per-turn (old) | (worse) | replaced |
| windowed chunking | 86.7% | adopt (2x faster, 12x fewer conv vectors) |
| + contextual embedding (`[meeting . date]` prefix) | 93.3% (+6.7) | **adopt - the real win** |
| + reranking (amazon.rerank-v1, Frankfurt) | 93.3% @10 / +3.3 @5 only | **decline - marginal** |

Verdict: promote **windowed + contextual** to production, ship-gated. Reranking declined on evidence
(contextual already saturated recall; Anthropic's biggest lever gave us +1 question). Built:
`pipeline/chunk_conversations.py`, `pipeline/add_context.py`, `evals/retrieval_eval.py`,
`evals/retrieval_braintrust.py`; `embed_corpus.py` parametrized.

Remaining before/after prod promotion:
- Verify the win holds under **hybrid** retrieval (production mode; the eval was semantic-lane only).
- Ruler is transcript-only - add a gmail slice for corpus-wide confidence; iMessage/gchat unmeasured.
- Then: re-chunk + re-embed the production `vectors.db` (windowed + contextual) behind the ship gate.
- The GENERATION eval (faithfulness + answer-correctness) is the separate next job.
