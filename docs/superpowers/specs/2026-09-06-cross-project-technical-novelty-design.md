# Cross-project technical novelty

**Date:** 2026-09-06

## Goal

The morning brief selects at most one fresh technical concept from recent work in any real Git project on Daniel's Mac.
The selection includes committed work, tracked edits, deletions, and untracked filenames.
The system does not copy full repositories, untracked contents, secrets, binaries, or generated output to EC2.

## Current failure

The EC2 brief reads only the top entry in `~/super-project/docs/CHANGELOG.md`.
That file has not changed since August 2026, while Agent Lab had recent work in September 2026.
The EC2 host cannot see Mac repositories, so prompt changes alone cannot fix the source gap.
The current technical history is also only a short text tail in the prompt.
Rephrasing the same concept therefore bypasses the existing check.

## Chosen design

A deterministic Mac script discovers Git repositories under Daniel's home folder.
It prunes system folders, package caches, virtual environments, generated output, dependency trees, tool histories, and skill or plugin installations.
Repository discovery is dynamic, so Agent Lab and future projects do not need a manual allowlist.

For each repository, the script reads Git metadata only.
It collects non-merge commits from a rolling 14-day window and the current working-tree status.
Committed events contain the repository slug, commit hash, commit time, subject, and changed paths.
Dirty-tree events contain the repository slug, a stable status fingerprint, recent tracked paths, deleted paths, and untracked filenames.
Dirty-tree contents and commit bodies are excluded.
Binary, lock, database, archive, media, environment, credential, generated, and dependency paths are excluded.

The script writes one versioned JSON snapshot atomically on the Mac.
It publishes that snapshot atomically to the EC2 host through the existing `twin-mind` SSH connection over AWS SSM.
No S3 bucket, public endpoint, repository mirror, or new credential path is added.
The LaunchAgent runs at login and shortly before the 07:30 brief.
If the Mac is unavailable, EC2 uses the last valid snapshot and its unsurfaced events.

## Selection and novelty

EC2 rejects snapshots with an unsupported schema or invalid records.
It removes stale events, exact event IDs already handled, and events without useful code or configuration paths.
It builds a compact candidate string from the project name, commit subject, and changed paths.
Exact event IDs prevent a delivered source change from returning to the shortlist.

Code groups related commits into work sessions before ranking them.
Commits belong to one cluster when they are in the same repository, occur within six hours, and touch overlapping paths.
This prevents a final small hardening commit from hiding the larger feature or architectural change it completed.

Code gives each surviving cluster an evidence score.
Production behavior, architecture, reliability, security, data integrity, tests, and safeguards raise the score.
Formatting, dependency bumps, generated output, and small documentation edits lower the score.
The deterministic score creates a shortlist of at most five clusters.

The existing composer call chooses the most useful transferable technical lesson from that shortlist.
System impact breaks ties between equally useful lessons.
The composer receives project names, commit subjects, times, and changed paths, but no source contents.
The structured output carries the selected cluster ID and project slug.
Code validates both against the shortlist, so the model cannot invent or select a hidden source.
This judgment happens inside the existing composition call and does not add another model request.

The final technical concept is checked semantically after composition against a dedicated `~/.hermes/state/seen-technical.jsonl` store.
If the result is too similar to a previously delivered concept, the renderer omits the technical section and marks the source event as rejected.
An embedding or store failure fails closed for the technical section, because repeating a lesson is worse than omitting one.
The successful check returns the new vector, which delivery records without another embedding call.
This does not trigger another model call.
If no fresh candidate exists, the brief omits the section instead of forcing an old queue item.

## Delivery state

The email sender return code is checked.
The pipeline records the source event ID and semantic text only after successful delivery.
A failed send records neither as delivered and reports failure instead of announcing success.

## Cost

A read-only benchmark on 2026-09-06 discovered 64 repositories and 36 recent events in 2.1 seconds.
The resulting snapshot was 10.7 KB.
The production schedule performs this scan once per day plus once at login.
It uses no web search and no Mac-side model call.
The existing brief keeps one composition call with a prompt similar in size to the current changelog input.
The novelty gate adds at most one small Cohere embedding batch on mornings with eligible project activity.

## Verification

Fixtures cover committed changes, tracked edits, deletions, untracked filenames, excluded paths, duplicate dirty fingerprints, stale snapshots, and atomic publication failure.
An end-to-end fixture includes recent Agent Lab commits and a stale Super Project changelog.
It must select Agent Lab and must reject a semantically repeated novelty-gate lesson.
The existing brief gate must pass before deployment.
A box-side dry run must show the selected project and source event without sending email.

## Rejected approaches

GitHub-only discovery misses local-only and uncommitted work.
Full repository or raw diff sync copies more source than the brief needs and raises secret risk.
Prompt-only dedup repeats concepts because labels and wording change.
