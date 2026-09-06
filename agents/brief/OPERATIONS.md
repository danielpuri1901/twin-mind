# Morning brief - operational notes (governed)
Salvaged 2026-07-13 from the twin's self-authored "morning-brief-infra-notes" (now deleted).
~85% of it was verified gold; false entries corrected. Credit where due: the twin discovered a
real send_email bug (missing datetime import, fixed) and the Tirith patterns below.

## Terminal security scanner (Tirith) - verified pitfalls
- `python3 -c "..."` is BLOCKED (script-execution guard). Write a .py to /tmp and run it.
- Emoji/Unicode variation selectors in email subject OR body block the send. Plain ASCII only.
- `himalaya` CLI is blocked for inbox reads. Use inbox_read.py.
- Safe send pattern: body already on disk -> `python3 send_email.py "Subject" < /tmp/body.txt`,
  or a /tmp python wrapper using list-form subprocess (no shell interpolation).

## Tool truths
- send_email.py: subject is POSITIONAL (no --subject flag). Success = exit 0 + "sent:" line +
  "heartbeat: BriefSent metric emitted". Cursor now writes correctly (datetime import fixed 07-13).
- calendar_read.py: flags are `--days N` ONLY. There is NO --today flag (a prior twin note claiming
  it "worked" was wrong - ungoverned notes drift). Empty output = genuinely no events, not an error.
  Times are LOCAL as of the 07-13 timezone fix.
- corpus-search does NOT index wiki/ markdown. For topic state: `cat ~/twin-corpus/wiki/topics/<t>.md`.
  Wiki "## Correction (Daniel...)" blocks are authoritative over corpus search results.

## Triage craft (verified patterns)
- Latest-state = BOTH steps, always: corpus-search the person/topic AND cat the wiki topic page.
- Granola notes from the last 24-48h are first-class triage sources (often richer than inbox);
  list_meetings first (cheap, in the parallel batch), then get_meetings([ids]) for relevant ones.
  Applies to academic events too (defenses, resits generate obligations).
- Parallel-gather at run start: inbox, calendar, Granola list, web - one batch, never serial.
- Calendar is the source of truth for travel; booking-confirmation emails are not action items.

## Inbox noise filter (skip): newsletters (Medium/NYT/Guardian/Daily Stoic), LinkedIn job alerts
(job search paused), Dutch retail promos (Thuisbezorgd etc.), SaaS onboarding, booking confirmations,
YC rejections without follow-up instructions.
## Always surface: AWS budget alerts, self-sent emails (Daniel's reminders to himself), unanswered
calendar invites from known contacts, supervisor emails with deadline language, bank security alerts.

## Cross-project technical activity

The Mac collector discovers Git repositories dynamically under Daniel's home folder.
It publishes commit metadata and changed filenames only.
It never publishes source contents, untracked contents, commit bodies, absolute paths, credentials, environment files, media, databases, generated output, dependency trees, or lockfiles.

Run and publish manually:

```bash
/usr/bin/python3 "/Users/danielpuri/Super Project/agents/brief/tools/collect_project_activity.py" --publish
```

The local snapshot is `~/twin-corpus/notes/project-activity.json`.
The remote snapshot is `/home/ec2-user/twin-corpus/notes/project-activity.json`.
Publication uses the existing `twin-mind` SSH host over AWS SSM.
The remote snapshot remains intact when collection, AWS authentication, SSH, or publication fails.
The brief ignores malformed snapshots and snapshots older than 30 days.
On the first run, the brief embeds the old `technical-covered.txt` topics once and atomically seeds the semantic novelty store.
If that migration fails, the technical section stays empty rather than forgetting prior lessons.

Install or refresh the LaunchAgent:

```bash
mkdir -p "$HOME/.hermes/logs"
cp "/Users/danielpuri/Super Project/agents/brief/com.twinmind.brief-project-activity.plist" "$HOME/Library/LaunchAgents/"
launchctl bootout "gui/$(id -u)/com.twinmind.brief-project-activity" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.twinmind.brief-project-activity.plist"
```

The job runs at login and at 07:00 local time before the 07:30 brief.
Its logs are `~/.hermes/logs/project-activity.out.log` and `~/.hermes/logs/project-activity.err.log`.

Remove the LaunchAgent:

```bash
launchctl bootout "gui/$(id -u)/com.twinmind.brief-project-activity"
rm "$HOME/Library/LaunchAgents/com.twinmind.brief-project-activity.plist"
```
