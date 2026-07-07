# Incident: EPERM on all project-file writes (2026-07-07)

## Symptom
Mid-session, Edit/Write tools and shell commands (touch, cat, python3 open(), git getcwd) began returning
"Operation not permitted" on files under ~/Desktop/Super Project - files owned by the user, mode rw, no BSD flags.
Reads from ~/twin-corpus (home, unprotected) kept working. The denial EXPANDED over ~20 minutes
(first only some writes failed, then all reads too) as processes accumulated cached deny verdicts.

## Root cause (proven, not guessed)
macOS TCC (privacy system) protects the Desktop folder per APPLICATION. Claude Code disclaims its host
terminal's TCC responsibility, so the TCC "client" is the versioned CLI binary itself:
    ~/.local/share/claude/versions/<version>
The user's TCC database (queried directly) shows Desktop-folder grants for versions 2.1.177 (Jun 15)
and 2.1.195 (Jun 27) - one grant per auto-update, each earned via a permission prompt.
At 01:24 on Jul 7, Claude Code auto-updated to 2.1.202 (symlink mtime). New binary path = new TCC client
= NO grant. macOS denied silently (CLI clients do not always get the consent dialog).
Full Disk Access being "already on" was irrelevant: it was on for other apps; the claude 2.1.202 binary
itself had no row.

## Why it looked bizarre
- Worked all week: the running session predated the update; helper invocations progressively resolved
  the NEW binary via the symlink, so denials appeared mid-session and spread.
- kitty (the terminal) HAS a Desktop grant - masked by Claude's responsibility disclaim.
- Home-directory paths (~/twin-corpus) are not TCC-protected: corpus work never broke.

## Fix
Permanent: grant Desktop access (or Full Disk Access) to the CURRENT claude version binary:
System Settings -> Privacy & Security -> Full Disk Access -> "+" -> Cmd+Shift+G ->
~/.local/share/claude/versions/<current> (or re-trigger the prompt from a fresh claude process).
NOTE: this re-breaks on every auto-update that changes the version path - known sharp edge.
Workaround used today: the uv-managed python3.11 binary carries its OWN Desktop grant (earned Jul 3),
so writes were routed through it.

## Lessons
1. TCC grants are per-binary-path for CLI tools; self-updating CLIs orphan their own permissions.
2. A silent OS deny looks identical to a code bug: check `ls -lO` (flags), then the process chain
   (ps to the responsible app), then TCC.db - in that order.
3. Time-correlate: the only state change on the machine was the 01:24 auto-update. "What changed?"
   beats "what's wrong?" as the first debugging question.

## Addendum: the per-file layer (proven same day)
Folder permission was only half the story. macOS Tahoe seals files with com.apple.macl - an ACL
binding each file to the app that CREATED it inside a protected folder. Proof: a binary holding its
own Desktop-folder grant (uv python3.11) could create+read NEW files in the same directory, but got
EPERM even LISTING XATTRS on files created by claude 2.1.19x. The auto-update therefore orphaned
both the folder grant AND per-file access to everything the old versions wrote.

## Fixes, ranked
1. PERMANENT (adopted): move the project out of TCC-protected folders. Desktop/Documents/Downloads
   are permission minefields for self-updating CLI tools; plain home paths (~) have no TCC at all -
   which is why ~/twin-corpus never broke. A symlink on Desktop can preserve Finder ergonomics.
2. Immediate: System Settings -> Privacy & Security -> Full Disk Access -> + -> Cmd+Shift+G ->
   ~/.local/share/claude/versions/<current>. FDA bypasses macl. Re-breaks on next auto-update.
