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
# The agent must not be able to rewrite its own bridge.
for f in /home/twin-chat/.letta/mods /home/twin-chat/.letta/mods/twin_mind.ts; do
  case "$(sudo -n lsattr -d "$f" 2>/dev/null | cut -d" " -f1)" in *i*) ;; *) echo "NOT IMMUTABLE $f"; fail=1 ;; esac
done
# A timer that is installed but not enabled never runs.
for f in infra/systemd/*.timer; do
  systemctl is-enabled --quiet "${f##*/}" || { echo "TIMER NOT ENABLED ${f##*/}"; fail=1; }
done
# Letta ships about two releases a day. The pin moves only after evals/chat_contract.sh passes on the new one.
have=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' /opt/letta/lib/node_modules/@letta-ai/letta-code/package.json | head -n 1)
[ "$have" = "$(cat infra/letta-version)" ] || { echo "LETTA VERSION installed $have, pinned $(cat infra/letta-version)"; fail=1; }
[ "$fail" = 0 ] && echo "PASS box matches main at $(git rev-parse --short HEAD)"
exit "$fail"
