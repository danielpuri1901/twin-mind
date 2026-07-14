# pipeline/fetch_granola - design + handoff (2026-07-14)

Status: validated, ready to build. Handoff to the terminal building `agents/background-prep`.
Both auth paths tried on Granola v7.394.3, macOS 15 (Daniel's machine). Path 2 proven end-to-end.

## Job

Every time a Granola meeting finishes and its transcript syncs, save the EXACT verbatim transcript
as one Markdown file in the corpus, then normalize + reindex so the twin knows the meeting within minutes.
This is the post-call mirror of background-prep's pre-call poller, on the same 15-min cadence.

Daniel's rulings (from brainstorm):
- Trigger: near-real-time, not manual.
- Contents: exact transcript + a small metadata header. Not the AI notes.
- Scope: only new meetings going forward. The 21 existing meetings are NOT backfilled.
- Depth: after writing the raw file, auto-run normalize + reindex (not just drop the file).

## Why it belongs here (not a separate artifact)

- `pipeline/` = Mac-only data prep (repo law). Granola ingestion is exactly that.
- Granola is an already-planned, unchecked source in `docs/ingestion-plan.md`.
- The transcript pipeline already exists: `raw/transcripts-inbox/*.md` -> `pipeline/normalize_transcripts.py`
  -> `normalized/transcripts.jsonl` -> `index/corpus.db` + `vectors.db`.
  Daniel's one hand-pasted file (`2026-07-02-tiffany-followup-rejection.md`) is already in the target format.
- It directly enriches background-prep: that agent reads prior Granola notes for "your history with them."
  Verbatim transcripts in the corpus make "call #2 knows what was actually said in call #1" real.
- Fully deterministic. No LLM in the ingestion path (honors Daniel's "as deterministic as possible").

## Auth: two paths tried, results

Granola v7.227+ (May 2026) encrypts local storage. The plaintext `supabase.json` is frozen (Daniel's: May 12).
The live token is in `supabase.json.enc`. So "read the plaintext token" is dead.

### Path 2 - local decrypt (RECOMMENDED for the Mac-side ingester)

PROVEN. Fully local, deterministic, no Claude, no per-run cost. Chain:

```
Keychain "Granola Safe Storage" / "Granola Key"   (macOS prompt = the auth gate; "Always Allow" once)
  -> Electron safeStorage: AES-128-CBC, key = PBKDF2-SHA1(pw, "saltysalt", 1003, 16), IV = 16x 0x20, PKCS7
  -> decrypt storage.dek (strip "v10" prefix) -> base64-decode -> 32-byte DEK
  -> AES-256-GCM(DEK) over supabase.json.enc, layout [12B IV][ciphertext][16B tag] -> live token JSON
  -> workos_tokens.access_token (Bearer) -> REST API
```

Working reference implementation (validated today):
`/private/tmp/claude-501/-Users-danielpuri/21efbb83-ffc0-4ac9-9d76-8754888116d9/scratchpad/granola_path2_decrypt.py`
Copy its `keychain_password / safestorage_decrypt / get_dek / decrypt_enc / api` functions into the tool.
Needs `cryptography` (already present: 46.0.5 system, 46.0.7 hermes venv).

Costs of Path 2:
- Brittle: Granola changed this scheme once already (May). An app update can break decryption. Mitigate with
  the dead-man's switch below - it must SCREAM, never silently drop meetings.
- Mac-only: needs the login Keychain, so this ingester runs on the Mac, not the box. That is correct anyway -
  the corpus lives on the Mac and rides the existing weekly Mac->box sync.
- Token freshness: the app auto-refreshes the encrypted token on launch/use (TTL ~6h; today's expired at 17:00 UTC).
  If Daniel's Granola app has not run in a while the decrypted token can be stale -> 401. Handle 401 as a soft
  "app not running" state, not a crash; retry next poll.
- launchd Keychain access: a background launchd job reading the Keychain needs the item ACL to allow
  `/usr/bin/security` (or the python binary) non-interactively. One-time setup; document it. First interactive
  run pops the "Always Allow" dialog.

### Path 3 - official Granola MCP (fallback / box-side)

Already connected and working in Claude (lists meetings, `get_meeting_transcript` available -> Daniel is on a
tier that unlocks MCP transcripts). OAuth, survives app updates, Granola-supported.
Costs: reintroduces a Claude dependency (a launchd job would shell to `claude -p` with a tight fetch prompt),
per-run token cost, and mild nondeterminism. Use only if Path 2's decryption breaks and is not quickly fixable.
Note: the official Personal API (`grn_` keys, `GET /v1/notes`) is the cleanest of all but is Business/Enterprise
only - not available on Daniel's plan as far as we could tell, so it is out for now.

## Transcript data contract (measured, not guessed)

`POST https://api.granola.ai/v1/get-document-transcript`  body `{"document_id": "<id>"}`  ->  array of segments.
Each segment (real keys observed): `document_id, id, start_timestamp, end_timestamp, text, source, is_final,
transcriber_user_id, detected_speaker_name`.

- `source`: `"microphone"` = Daniel -> `Me:` ; `"system"` = other party -> `Them:`.
- `detected_speaker_name`: real name when Granola has it - optionally use for a richer label, but the normalizer
  only understands `Me:` / `Them:` today, so keep the body strictly `Me:`/`Them:` unless the normalizer is extended.
- Collapse consecutive same-source segments into one turn (matches Granola's own export and reads better).
- Responses are gzip-encoded - decompress (check `Content-Encoding` / `1f 8b` magic).
- Document list: `POST /v2/get-documents` `{"limit": N}` -> `{docs: [...]}`; each doc has `id`, `title`,
  `created_at`, and attendee/people metadata for the header.

## Output file (matches existing format + normalizer)

Write to `~/twin-corpus/raw/transcripts-inbox/YYYY-MM-DD-<slug>.md`, slug from the title (kebab, deduped).

```
Meeting Title: <title>
Date: <Mon DD, YYYY>
Participants: <names>
(Exact Granola transcript, auto-saved <YYYY-MM-DD>.)

Them: Hello, Daniel. Hello, Anthony.
Me: Hello everybody.
...
```

`normalize_transcripts.py` ignores the header (only `^(Me|Them):` lines become records) so this drops straight in.

REQUIRED one-line change to `pipeline/normalize_transcripts.py`: its `SOURCES` are hardcoded to
`~/Desktop/Career/...` and do NOT yet read the inbox. Add:
`glob.glob(os.path.join(HOME, "twin-corpus/raw/transcripts-inbox/*.md"))`
This also finally wires in the existing hand-pasted file.

## Poller architecture (mirror scan_meetings.py exactly)

Same house pattern as `agents/background-prep/tools/scan_meetings.py`:

- Runs every 15 min, deterministic, no LLM. On the Mac (launchd) because Path 2 needs the Keychain.
  (background-prep's poller is box-side hermes-cron; this one is Mac-side launchd - same cadence + doctrine,
  different host, because the credential + corpus are Mac-local.)
- State: `~/.hermes/state/transcript-state.json`  ->  `{document_id: {status, ts, meeting}}`.
  status in {saved, failed}. Dedup key = `document_id` (never re-save).
- FIRST RUN = "only new going forward": seed state by marking every current document_id as `seen-baseline`
  (do NOT write files for them). Only docs that appear AFTER the baseline get saved. This enforces Daniel's scope.
- Only save a doc when its transcript looks final (segments exist and `is_final` is set on the tail) - avoids
  half-saving a meeting still being transcribed. Re-check on the next poll until stable.
- After writing new file(s): run `normalize_transcripts.py` then `build_index.py` (+ embed step) so the meeting
  is searchable within minutes. Guard with a lock so it never overlaps a manual corpus refresh.
- Heartbeat: CloudWatch `put-metric-data --namespace TwinMind --metric-name TranscriptPollerRan --value 1`.
  Dead-man's switch on that metric (same alarm path as PrepPollerRan): staleness -> same-day Telegram alert.
  Same alarm fires on repeated 401s (token stale = app not running) and on decryption failure (Granola updated).
- Silent when healthy; print only actions and problems.

## Timing tie-in with background-prep

- background-prep poller: fires ~60 min BEFORE a qualifying call, delivers a dossier.
- transcript-ingest poller: fires AFTER a call, when Granola finishes transcribing, saves the verbatim transcript.
- Same 15-min cadence, same state/heartbeat/dead-man doctrine, same corpus. They are the before/after halves of
  one meeting loop. No shared code needed beyond the corpus contract, but keep the poller idioms identical so a
  future reader sees one pattern.

## Open questions for the implementing terminal

1. Host + scheduler: Mac launchd (Path 2, recommended) vs box hermes-cron+MCP (Path 3). Confirm launchd, since
   Path 2 is Mac-bound. If the box must own it, that forces Path 3.
2. Speaker labels: keep strict `Me:`/`Them:`, or extend `normalize_transcripts.py` to consume
   `detected_speaker_name` for multi-party calls? (Deferred; strict Me/Them ships first.)
3. "Final transcript" heuristic: is `is_final` on the last segment sufficient, or add a settle delay
   (e.g. only save meetings whose `created_at` is >10 min old)?
4. Reindex cost: full `build_index.py` per meeting vs an incremental append. Start with full; measure.

## Validation artifacts (this session)

- `scratchpad/granola_api_probe.py` - first probe; surfaced that plaintext token is stale (401).
- `scratchpad/granola_path2_decrypt.py` - PROVEN Path 2: decrypt -> live token -> 1034-segment real transcript.
