# Cross-project Technical Novelty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the morning brief choose a fresh, transferable technical lesson from recent work across every real Git project on Daniel's Mac.

**Architecture:** A Mac-side Python collector reads Git metadata and publishes a small derived snapshot to EC2 through the existing SSH-over-SSM host.
The EC2 brief clusters related changes, filters semantic repeats, shortlists meaningful work sessions, and uses its existing composition call to choose the best transferable lesson.

**Tech Stack:** Python 3 standard library, Git CLI, launchd, SSH over AWS SSM, Pydantic, and the existing Cohere Bedrock novelty store.

**Spec:** `docs/superpowers/specs/2026-09-06-cross-project-technical-novelty-design.md`

## Global Constraints

The collector scans Git metadata only.
It never publishes file contents, untracked contents, commit bodies, author data, full absolute paths, secrets, binaries, databases, media, generated output, dependency trees, or lockfiles.
The snapshot is versioned and replaced atomically on both machines.
The Mac performs no model or search call.
The brief keeps one composition call.
Technical novelty failures fail closed by omitting the section.
The AI-news novelty stream keeps its current fail-open behavior.
No new package or AWS service is introduced.
The section may be absent when no fresh lesson exists.
State is recorded only after successful email delivery.

---

## File map

- Create `agents/brief/tools/collect_project_activity.py` for repository discovery, Git metadata collection, snapshot writing, and SSM-backed publication.
- Create `evals/test_project_activity_collector.py` for temporary-repository end-to-end tests of the Mac collector.
- Create `agents/brief/tools/project_activity.py` for snapshot validation, change clustering, evidence scoring, exact consumption state, and semantic shortlisting.
- Create `evals/test_project_activity.py` for deterministic clustering, ranking, stale-data, and failure-mode tests.
- Modify `shared/novelty.py` to let callers choose fail-open or fail-closed behavior without changing the AI-news default.
- Modify `agents/brief/tools/compose_brief.py` to replace the Super Project changelog source with the validated cross-project shortlist.
- Modify `agents/brief/tools/prefetch.py` to remove the retired single-repository and rotating fallback sources.
- Modify `evals/brief_checks.py`, `evals/test_brief_checks.py`, `agents/brief/tools/brief_check.py`, and `evals/test_brief_check.py` so the technical section is optional but validated when present.
- Modify `evals/eval.sh` so the deterministic ship gate runs both new test scripts.
- Create `agents/brief/com.twinmind.brief-project-activity.plist` for login and pre-brief publication.
- Modify `agents/brief/OPERATIONS.md` with install, manual-run, state, and failure instructions.

---

### Task 1: Collect a safe Git activity snapshot on the Mac

**Files:**

- Create: `agents/brief/tools/collect_project_activity.py`
- Create: `evals/test_project_activity_collector.py`

**Interfaces:**

- Produces: `discover_repositories(home: Path) -> list[Path]`
- Produces: `collect_snapshot(home: Path, now: datetime, lookback_days: int = 14) -> dict`
- Produces: `write_snapshot(snapshot: dict, destination: Path) -> None`
- Produces: `publish_snapshot(source: Path, remote_host: str, remote_path: str) -> None`
- Produces CLI: `collect_project_activity.py [--home PATH] [--output PATH] [--publish]`

- [ ] **Step 1: Write the failing collector tests**

Create two temporary Git repositories and configure local commit identity inside each fixture.
Commit related Python changes in one repository and create tracked, deleted, and untracked changes in the other.

```python
class CollectorTests(unittest.TestCase):
    def test_snapshot_includes_names_without_contents(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            repo = make_repo(home / "agentlab")
            commit(repo, "feat: add guarded story generation", {"worker.py": "SECRET_BODY"})
            (repo / "worker.py").write_text("CHANGED_SECRET")
            (repo / "draft.py").write_text("UNTRACKED_SECRET")

            encoded = json.dumps(collector.collect_snapshot(home, NOW))

            self.assertIn("worker.py", encoded)
            self.assertIn("draft.py", encoded)
            self.assertNotIn("SECRET_BODY", encoded)
            self.assertNotIn("CHANGED_SECRET", encoded)
            self.assertNotIn("UNTRACKED_SECRET", encoded)

    def test_discovery_prunes_vendor_and_history_directories(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw)
            wanted = make_repo(home / "Projects" / "agentlab")
            make_repo(home / ".gemini" / "history" / "copy")
            make_repo(home / "app" / "node_modules" / "package")

            self.assertEqual(collector.discover_repositories(home), [wanted])
```

- [ ] **Step 2: Run the collector tests and verify the expected import failure**

Run: `python3 evals/test_project_activity_collector.py`

Expected: FAIL because `collect_project_activity.py` does not exist.

- [ ] **Step 3: Implement repository discovery and metadata collection**

Use `os.walk()` with an explicit pruned-directory set.
Do not impose a depth limit, because a real project may live deeper under the home folder.
Use list-form `subprocess.run()` calls to `git -C <repo>` with five-second timeouts.
Collect at most 20 non-merge commits per repository from the last 14 days.
Use `%H`, `%ct`, and `%s` plus `--name-only` for commit metadata.
Use `git status --porcelain=v1 --untracked-files=normal` for working-tree names.
Build dirty fingerprints from normalized status lines, never from file bytes.
Use file modification time only to avoid importing old dirty trees during bootstrap.

```python
EXCLUDED_DIRS = {
    "Library", ".Trash", ".cache", ".local", ".nvm", ".gemini",
    ".codex", ".claude", ".agents", ".hermes", "node_modules",
    ".venv", "venv", "dist", "build", "out", "__pycache__",
}

EXCLUDED_SUFFIXES = {
    ".lock", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mov",
    ".zip", ".pdf", ".db", ".sqlite", ".pem", ".key",
}

EXCLUDED_NAMES = {".env", ".env.local", "credentials", "credentials.json"}

def dirty_event_id(status_lines: list[str]) -> str:
    normalized = "\n".join(sorted(status_lines))
    return "dirty:" + hashlib.sha256(normalized.encode()).hexdigest()
```

- [ ] **Step 4: Implement atomic local writing and remote publication**

Write JSON to a sibling temporary file, flush it, call `os.fsync()`, and replace the destination with `os.replace()`.
Publish with `rsync --delay-updates` to the existing `twin-mind` SSH host.
Publish only the one snapshot file.
Return a nonzero process exit when collection or publication fails.

```python
def publish_snapshot(source: Path, remote_host: str, remote_path: str) -> None:
    subprocess.run(
        ["rsync", "--delay-updates", "--chmod=F600", str(source),
         f"{remote_host}:{remote_path}"],
        check=True,
        timeout=60,
    )
```

- [ ] **Step 5: Run the collector tests**

Run: `python3 evals/test_project_activity_collector.py`

Expected: PASS, including the assertion that fixture source contents never enter the JSON snapshot.

- [ ] **Step 6: Commit the collector**

```bash
git add agents/brief/tools/collect_project_activity.py evals/test_project_activity_collector.py
git commit -m "feat: collect cross-project Git activity"
```

---

### Task 2: Cluster, rank, and semantically filter technical candidates

**Files:**

- Create: `agents/brief/tools/project_activity.py`
- Create: `evals/test_project_activity.py`
- Modify: `shared/novelty.py`

**Interfaces:**

- Produces: `ActivityCluster` with `cluster_id`, `project`, `event_ids`, `latest_time`, `subjects`, `paths`, `score`, and `candidate_text`.
- Produces: `load_snapshot(path: str, now: datetime, max_age_days: int = 30) -> list[dict]`
- Produces: `cluster_events(events: list[dict], window_hours: int = 6) -> list[ActivityCluster]`
- Produces: `shortlist(path: str, handled_path: str, limit: int = 5) -> list[ActivityCluster]`
- Produces: `record_handled(cluster: ActivityCluster, status: str, path: str) -> None`
- Extends: `filter_novel(candidates, store=AI_STORE, threshold=0.80, fail_open=True) -> list[str]`
- Produces: `filter_novel_with_vectors(candidates, store=AI_STORE, threshold=0.80, fail_open=True) -> list[tuple[str, list[float]]]`

- [ ] **Step 1: Write failing clustering and novelty tests**

```python
class ProjectActivityTests(unittest.TestCase):
    def test_related_agentlab_commits_become_one_work_session(self):
        clusters = activity.cluster_events([
            event("a", "agentlab", 1000, "feat: compose story videos", ["worker.py"]),
            event("b", "agentlab", 2000, "fix: enforce timing limits", ["worker.py", "video.py"]),
            event("c", "agentlab", 3000, "fix: harden story quality", ["video.py"]),
        ])

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].event_ids, ("a", "b", "c"))

    def test_shortlist_prefers_technical_work_over_docs_and_dependencies(self):
        with tempfile.TemporaryDirectory() as raw:
            snapshot, handled, _seen = snapshot_with_feature_docs_and_bump(Path(raw))
            rows = activity.shortlist(str(snapshot), str(handled))

            self.assertEqual(rows[0].project, "agentlab")
            self.assertTrue(all("dependency bump" not in row.candidate_text for row in rows))

    def test_technical_novelty_fails_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            store = Path(raw) / "seen.jsonl"
            store.write_text(json.dumps({"text": "old", "vec": [1.0]}) + "\n")
            with mock.patch.object(novelty, "_embed", side_effect=RuntimeError("down")):
                self.assertEqual(novelty.filter_novel(["candidate"], store=str(store), fail_open=False), [])
                self.assertEqual(novelty.filter_novel(["candidate"], store=str(store), fail_open=True), ["candidate"])
```

- [ ] **Step 2: Run the selection tests and verify failure**

Run: `python3 evals/test_project_activity.py`

Expected: FAIL because `project_activity.py` and the `fail_open` option do not exist.

- [ ] **Step 3: Add strict novelty behavior without changing AI news**

Add `fail_open: bool = True` to `shared.novelty.filter_novel()`.
Return the candidates on error when `fail_open` is true.
Return an empty list on error when `fail_open` is false.
Treat a missing store as a valid empty history.
Treat malformed rows or stored rows without vectors as an error in fail-closed mode.
Keep every existing caller unchanged so AI news remains fail-open.
Add `filter_novel_with_vectors()` so the technical section can reuse the checked vector when recording.
Add an optional `vectors` argument to `record()` so supplied vectors avoid another embedding request.

- [ ] **Step 4: Implement snapshot validation and exact consumption state**

Reject malformed JSON, unsupported schema versions, records without required types, and snapshots older than 30 days.
Read handled event IDs from an append-only JSONL file.
Exclude every cluster whose event IDs are all handled.
Write one JSONL row with date, cluster ID, status, and every event ID when recording a handled cluster.

- [ ] **Step 5: Implement work-session clustering**

Sort events by project, event time, and event ID.
Join adjacent events only when they occur within six hours and their normalized path sets overlap.
Allow transitive overlap within a cluster.
Compute `cluster_id` as SHA-256 over the sorted event IDs.

- [ ] **Step 6: Implement evidence scoring and shortlisting**

Award evidence for production source paths, tests, infrastructure, and subjects containing `feat`, `fix`, `security`, `harden`, `guard`, `retry`, `migrate`, `refactor`, `perf`, or `architecture`.
Penalize documentation-only, formatting-only, generated-only, dependency-only, and merge activity.
Use the score only to reduce the set to five clusters.
Sort equal scores by latest activity descending, project slug, and cluster ID.
Return the top five unhandled clusters without an embedding request.
The exact event store removes reused source changes before composition.

- [ ] **Step 7: Run the selection and existing novelty tests**

Run: `python3 evals/test_project_activity.py`

Run: `python3 -m py_compile shared/novelty.py agents/brief/tools/project_activity.py`

Expected: PASS.

- [ ] **Step 8: Commit selection and strict novelty**

```bash
git add shared/novelty.py agents/brief/tools/project_activity.py evals/test_project_activity.py
git commit -m "feat: rank and gate technical work sessions"
```

---

### Task 3: Integrate the shortlist into the morning brief

**Files:**

- Modify: `agents/brief/tools/compose_brief.py`
- Modify: `agents/brief/tools/prefetch.py`
- Modify: `evals/brief_checks.py`
- Modify: `evals/test_brief_checks.py`
- Modify: `agents/brief/tools/brief_check.py`
- Modify: `evals/test_brief_check.py`
- Modify: `evals/eval.sh`

**Interfaces:**

- Changes: `TechnicalThing` fields become `source_id`, `project`, `topic`, `concept`, `quiz`, and `answer`.
- Changes: `Brief.technical_thing` becomes `TechnicalThing | None`.
- Produces: `validate_technical_source(brief: Brief, candidates: list[ActivityCluster]) -> ActivityCluster | None`
- Produces: `technical_text(thing: TechnicalThing) -> str`

- [ ] **Step 1: Update tests first for optional and source-bound technical output**

Add cases proving that a brief without a technical section passes structural and watchdog checks.
Add cases proving that a present technical section requires every new field.
Add cases proving that an invented source ID is rejected.
Add an end-to-end fixture with recent Agent Lab activity and a stale Super Project changelog, then assert that only Agent Lab enters the technical shortlist.
Remove the old Super Project code-symbol fixture because external source bytes no longer exist on EC2.

```python
def test_sections_present_allows_no_fresh_technical_item():
    brief = _good_brief()
    brief["technical_thing"] = None
    assert BC.sections_present(brief).passed


def test_validate_technical_source_rejects_hidden_source():
    brief = brief_with_source("invented", "agentlab")
    assert compose.validate_technical_source(brief, [cluster("real", "agentlab")]) is None
```

- [ ] **Step 2: Run the brief tests and verify failure**

Run: `python3 evals/test_brief_checks.py`

Run: `python3 evals/test_brief_check.py`

Expected: FAIL under the old mandatory technical schema and five-section watchdog contract.

- [ ] **Step 3: Replace changelog and rotating fallback inputs**

Load `project_activity.shortlist()` in `gather_facts()`.
Remove `changelog`, `technical_item`, and the truncated `technical_taught` prompt inputs.
Delete the now-unused `prefetch.technical_item()` and `prefetch.changelog_top()` functions.
Format at most five candidates with stable IDs, project names, timestamps, subjects, and changed paths.
Tell the model to choose the most useful transferable lesson first and use system impact as the tiebreaker.
Tell it to return null when the shortlist is empty.

- [ ] **Step 4: Validate source selection and post-compose novelty**

Check that `source_id` and `project` exactly match one shortlisted cluster.
Check `topic + concept` with `filter_novel_with_vectors()` against the dedicated technical novelty store and `fail_open=False`.
If either check fails, replace `brief.technical_thing` with null and retain the rejected cluster for handled-state recording after delivery.
Reuse the returned vector when recording a delivered concept.
Do not retry composition.

- [ ] **Step 5: Render the optional section and correct delivery state**

Render `ONE TECHNICAL THING` only when `technical_thing` is present.
Render `From project: <project>` for source provenance.
Call `send_email.py` with `check=True`.
After successful send, record the delivered semantic text and exact cluster event IDs.
After a successful email that omitted a duplicate or invalid result, record the rejected cluster status without adding it to the semantic store.
On send failure, raise and record no technical state.

- [ ] **Step 6: Update watchdog and deterministic checks**

Require the four always-present section headers.
Allow the technical header to be absent.
When the technical header exists, still require the answer line and all structured fields.
Remove `code_symbol_real` from `run_all()` because the activity feed intentionally contains no source bytes.
Add both new test scripts to the deterministic portion of `evals/eval.sh`.

- [ ] **Step 7: Run focused brief tests**

Run: `python3 evals/test_project_activity_collector.py`

Run: `python3 evals/test_project_activity.py`

Run: `python3 evals/test_brief_checks.py`

Run: `python3 evals/test_brief_check.py`

Expected: PASS.

- [ ] **Step 8: Commit brief integration**

```bash
git add agents/brief/tools/compose_brief.py agents/brief/tools/prefetch.py agents/brief/tools/brief_check.py evals/brief_checks.py evals/test_brief_checks.py evals/test_brief_check.py evals/eval.sh
git commit -m "feat: teach from novel cross-project work"
```

---

### Task 4: Schedule, verify, and deploy the activity feed

**Files:**

- Create: `agents/brief/com.twinmind.brief-project-activity.plist`
- Modify: `agents/brief/OPERATIONS.md`

**Interfaces:**

- LaunchAgent label: `com.twinmind.brief-project-activity`
- Local snapshot: `~/twin-corpus/notes/project-activity.json`
- EC2 snapshot: `/home/ec2-user/twin-corpus/notes/project-activity.json`
- Logs: `~/.hermes/logs/project-activity.out.log` and `~/.hermes/logs/project-activity.err.log`

- [ ] **Step 1: Create the LaunchAgent definition**

Use `/usr/bin/python3` and the canonical script path in `/Users/danielpuri/Super Project`.
Set `RunAtLoad` to true.
Set a `StartCalendarInterval` for 07:00 local time.
Set `HOME` and a PATH containing `/usr/bin`, `/bin`, `/usr/sbin`, `/sbin`, `/usr/local/bin`, and `/opt/homebrew/bin`.
Send stdout and stderr to the dedicated Hermes log files.

- [ ] **Step 2: Document operations**

Document the exact manual collection command, snapshot paths, launchctl install and removal commands, exclusion boundary, stale-snapshot behavior, and log locations.
Document that the job exits nonzero when AWS authentication or SSM publication fails and keeps the previous remote snapshot intact.

- [ ] **Step 3: Validate the plist and full deterministic suite**

Run: `plutil -lint agents/brief/com.twinmind.brief-project-activity.plist`

Run: `python3 -m py_compile agents/brief/tools/collect_project_activity.py agents/brief/tools/project_activity.py agents/brief/tools/compose_brief.py shared/novelty.py`

Run: `python3 evals/test_project_activity_collector.py`

Run: `python3 evals/test_project_activity.py`

Run: `python3 evals/test_brief_checks.py`

Run: `python3 evals/test_brief_check.py`

Expected: PASS.

- [ ] **Step 4: Run the repository ship gate**

Run: `evals/eval.sh`

Expected: `EVAL GATE: GREEN`.

- [ ] **Step 5: Commit operations**

```bash
git add agents/brief/com.twinmind.brief-project-activity.plist agents/brief/OPERATIONS.md
git commit -m "ops: publish project activity before briefs"
```

- [ ] **Step 6: Install and run the Mac LaunchAgent**

Copy the plist to `~/Library/LaunchAgents/com.twinmind.brief-project-activity.plist`.
Boot out any old instance of the same label.
Bootstrap the new plist for `gui/$(id -u)`.
Confirm `launchctl list` reports the label and exit status zero.

- [ ] **Step 7: Verify the real Mac snapshot**

Run the collector once with `--publish`.
Check that the snapshot contains Agent Lab activity and contains no absolute home path or source bytes.
Check that its size stays below 100 KB.

- [ ] **Step 8: Deploy the changed runtime files to EC2**

Use `rsync` through the existing `twin-mind` host to deploy only `compose_brief.py`, `prefetch.py` if changed, `project_activity.py`, `novelty.py`, and the deterministic check files.
Do not sync unrelated repository files.
Compile the deployed Python files on EC2.

- [ ] **Step 9: Run an EC2 dry run without sending email**

Run `compose_brief.py --dry-run` on EC2.
Verify that the selected technical source is one of the published clusters.
Verify that Agent Lab can be selected while the stale Super Project changelog is ignored.
Verify that the command sends no email and writes no delivered novelty state.

- [ ] **Step 10: Final verification**

Compare Git status against the pre-existing unrelated changes.
Confirm those unrelated changes remain byte-for-byte untouched.
Confirm the worktree commits contain no generated snapshot, logs, credentials, or raw source data.
