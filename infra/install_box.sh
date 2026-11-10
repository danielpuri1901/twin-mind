#!/bin/sh
# Makes the copies installed outside the checkout equal the repo: the systemd units, the sudo rule,
# the Letta wrapper, the chat mod and the governed skills. infra/check_box.sh proves the result.
# infra/deploy_box.sh runs this after the checkout. It changes only what differs. It restarts chat
# only when the mod, a skill or the chat unit changed, and only after the turn in progress has ended.
# Usage on the box: sh ~/super-project/infra/install_box.sh
set -eu
cd "$HOME/super-project"
differs() { ! sudo -n cmp -s "$1" "$2"; }
reload=0
restart=0
enable=""

for f in infra/systemd/*; do
  name=${f##*/}
  target="/etc/systemd/system/$name"
  if differs "$f" "$target"; then
    # A timer that is new on this box gets enabled. A timer that exists keeps the state it has.
    case "$name" in
      *.timer) if ! sudo -n test -e "$target"; then enable="$enable $name"; fi ;;
    esac
    sudo -n install -o root -g root -m 644 "$f" "$target"
    reload=1
    if [ "$name" = twin-chat.service ]; then restart=1; fi
    echo "installed $name"
  fi
done

if differs infra/sudoers/twin-chat /etc/sudoers.d/twin-chat; then
  # A sudo rule that does not parse would lock the chat tools out, so check it first.
  sudo -n visudo -cf infra/sudoers/twin-chat >/dev/null
  sudo -n install -o root -g root -m 440 infra/sudoers/twin-chat /etc/sudoers.d/twin-chat
  echo "installed the sudo rule"
fi

if differs infra/bin/twin-chat-letta /usr/local/bin/twin-chat-letta; then
  sudo -n install -o root -g root -m 755 infra/bin/twin-chat-letta /usr/local/bin/twin-chat-letta
  echo "installed twin-chat-letta"
fi

# The mod and its folder are immutable, so the agent cannot rewrite its own bridge.
# The flag comes off only for the copy and goes back on in every run.
mods=/home/twin-chat/.letta/mods
if differs agents/chat/mods/twin_mind.ts "$mods/twin_mind.ts"; then
  sudo -n chattr -i "$mods" 2>/dev/null || true
  sudo -n chattr -i "$mods/twin_mind.ts" 2>/dev/null || true
  sudo -n install -o root -g root -m 644 agents/chat/mods/twin_mind.ts "$mods/twin_mind.ts"
  restart=1
  echo "installed the chat mod"
fi
sudo -n chattr +i "$mods/twin_mind.ts" "$mods"

for f in agents/chat/skills/*/SKILL.md; do
  target="/home/twin-chat/.letta/skills/${f#agents/chat/skills/}"
  if differs "$f" "$target"; then
    sudo -n install -D -o root -g root -m 644 "$f" "$target"
    restart=1
    echo "installed skill ${f#agents/chat/skills/}"
  fi
done

if [ "$reload" = 1 ]; then sudo -n systemctl daemon-reload; fi
for name in $enable; do
  sudo -n systemctl enable --now "$name"
  echo "enabled $name"
done

if [ "$restart" = 1 ]; then
  # While chat works on a message, the last chat-log row is that message. Wait for the answer,
  # for at most five minutes, so the restart does not cut a turn.
  "$HOME/.twin-mind/venv/bin/python" - <<'PY'
import sys
import time

sys.path.insert(0, "shared")
import chat_log

deadline = time.time() + 300
while time.time() < deadline:
    rows = chat_log.read()
    if not rows or rows[-1]["role"] != "user" or time.time() - rows[-1]["ts"] > 300:
        break
    time.sleep(5)
PY
  sudo -n systemctl restart twin-chat
  sleep 15
  systemctl is-active --quiet twin-chat || { echo "twin-chat did not come back after the restart"; exit 1; }
  echo "restarted twin-chat"
fi
