# Retired cloud routines - full prompts archived 2026-07-03

Daniel retired his three cloud routines when Twin Mind took over.
Replacement: skills/morning-brief/SKILL.md + Hermes cron.
Job-search scanning is PAUSED per Daniel (2026-07-02).
Below are the verbatim prompts so nothing is lost. Reusable assets flagged inline.

---

## 1. "Daily agent — Daniel (merged)" (trig_01SyDk2oohDQQFNig3jWuwdb, daily 05:27 UTC, was LIVE)

REUSABLE ASSETS: Notion config page id=374f8c2f-dbb5-8181-a5ae-ecac7f7e27a5 ("daily-agent — config"),
state page id=374f8c2f-dbb5-81d8-af2b-e3e43c88ac7d, digest page id=374f8c2f-dbb5-81cd-a5d8-c6997950dd93.
Dedup-key design (sha1 company|title|city), provenance footers, context-discipline pattern (compact notes, drop raw HTML).

Prompt summary (structure): STEP 0 load config+state from Notion -> STEP 1 gather sequentially
(1a Gmail triage 24h; 1b Calendar today+tomorrow; 1c Granola last 14d filtered to attendees;
1d Jobs via 26 LinkedIn URLs w/ dedup vs state.seen_jobs [PAUSED]; 1e GitHub repos big-picture 7d;
1f Discovery: GH trending weekly + Show HN 7d via Algolia + curated builders [karpathy, simonw,
jeremyhoward, antirez, ggerganov] + org releases [anthropics, openai, anysphere, vercel, modal-labs,
huggingface, langchain-ai, replicate, pinecone-io, perplexity-ai] + blog RSS [Anthropic/OpenAI/LangChain];
1g Learning topic from curriculum by day_index since 2026-05-13; 1h News AI/tech 4 + big-picture 2-3 + top-3 HN)
-> STEP 2 email, ACTION BLOCK first, <=1600 words -> STEP 3 Gmail DRAFT only -> STEP 4 persist state
to Notion, prune seen_jobs >75d. GUARDRAILS: drafts only, never contact anyone but Daniel, no LinkedIn
login, no customer names or EUR figures, never fabricate; per-source provenance footer `OK (n)` / FAILED.

## 2. "Daily morning brief — Daniel" (trig_01Hb93H6w6NPvmtbCLeaGnQD, dormant since Jun 3)

REUSABLE ASSETS: the full 26-week learning curriculum table (Phases 1-4: Missing Semester / CS50 /
Karpathy micrograd+makemore+GPT / fast.ai / Nand2Tetris / CS:APP / PMPP / Raschka / Huyen, plus Sunday
rotation: Jensen Huang Stanford 2024, Collison x Cowen, Carmack Lex 309, Karpathy agents talk,
YC Altman lecture, PG essays, Software 2.0, Collison x Klein). Canonical local copy of the curriculum:
~/Desktop/Learning/00-roadmap.md (routine carried a duplicate; roadmap file remains source of truth).
Section structure: inbox triage buckets / calendar w/ prep cues / Granola cross-ref / job-search pulse
[PAUSED] / GitHub project-state + discovery (3-5 items, quality bar, skip-list: crypto, awesome-lists,
courses) / suggested tasks 3-5 imperative / tomorrow heads-up / news 2 buckets w/ source lists /
top-3 HN weekly via Algolia / learning topic w/ recall prompt + 3 Anki stubs. Delivery: Gmail draft.

## 3. "Daily LinkedIn NG NYC On-Site Scan" (trig_014tqWb91j3Z8FCr52RAps7L, dormant)

Job-search scanner: 26 LinkedIn public URLs (NYC 9, Spain 5, Paris 5, SF-PM 4, Lux 3) with
f_TPR=r86400, f_E=1,2,3, f_WT=1. Apply filter mirrors ~/Desktop/Career/CLAUDE.md (geo priority,
on-site only, HARD 3+ YOE reject, NG archetypes, PM hard-rejects). Tiering: T1 clean NG / T2 unknown
firms / rejected-with-reasons. Output: Gmail draft + Notion rolling page. Fully reconstructible from
Career/CLAUDE.md + career-ops config; URL list preserved in career-ops portals.yml pattern.

---

Useful commands preserved:
- Show HN last 7d: curl -s "https://hn.algolia.com/api/v1/search?tags=show_hn&numericFilters=created_at_i>$(( $(date +%s) - 604800 ))&hitsPerPage=50"
- Top HN 7d: same with tags=story, hitsPerPage=3
