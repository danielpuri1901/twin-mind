#!/bin/sh
# Proves the box runs main: the live folder is a clean checkout of main, and
# each file installed outside the folder equals the repo. Exit 0 only if all match.
# Run on the box. It compares installed copies and does not install them.
set -u
cd "$HOME/super-project" || exit 1
fail=0
same() { sudo -n cmp -s "$1" "$2" || { echo "DIFFERS $1 and $2"; fail=1; }; }
git fetch --quiet origin main || { echo "FETCH FAILED"; fail=1; }
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "NOT AT MAIN: $(git rev-parse --short HEAD), main is $(git rev-parse --short origin/main)"; fail=1; }
[ -z "$(git status --porcelain)" ] || { echo "HAND EDITS:"; git status --short; fail=1; }
for f in infra/systemd/*; do same "$f" "/etc/systemd/system/${f##*/}"; done
same infra/sudoers/twin-chat /etc/sudoers.d/twin-chat
same infra/bin/twin-chat-letta /usr/local/bin/twin-chat-letta
same agents/chat/mods/twin_mind.ts /home/twin-chat/.letta/mods/twin_mind.ts
for f in agents/chat/skills/*/SKILL.md; do same "$f" "/home/twin-chat/.letta/skills/${f#agents/chat/skills/}"; done
[ "$fail" = 0 ] && echo "PASS box matches main at $(git rev-parse --short HEAD)"
exit "$fail"
