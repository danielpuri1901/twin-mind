#!/bin/sh
# The chat contract: one Telegram message in, one answer out, through the real harness.
#
# It runs real Letta in a throwaway home, with the adapter from this checkout, a fake Telegram on
# localhost and a temp chat log, so it touches no production state. One model call, a few cents.
# One turn proves three things that no unit test can:
#   1. Letta loads the adapter and fires its turn events.
#   2. The context added at turn start reaches the model. The answer needs the weekday, and the
#      prompt tells the model to say MISSING when it has no twin-mind-context block.
#   3. An answer that the model leaves as plain text still arrives, and the chat log has both rows.
# Headless Letta offers no MessageChannel tool, so every answer here is plain text. That is the
# failure that lost four answers between 2026-11-07 and 2026-11-10.
#
# Usage on the box: sh evals/chat_contract.sh [path/to/twin_mind.ts]
# Before a Letta upgrade: install the new version under another prefix, then run this with
# LETTA=/that/prefix/bin/letta. Change infra/letta-version only when it passes.
set -eu
cd "$(dirname "$0")/.."
MOD=${1:-agents/chat/mods/twin_mind.ts}
LETTA=${LETTA:-/opt/letta/bin/letta}
MODEL=${TWIN_CHAT_MODEL:-anthropic/claude-sonnet-5-5}
fail() { echo "CHAT CONTRACT: FAIL - $1"; exit 1; }

# An adapter without these overrides would write to the real chat log and talk to the real bot.
for name in TWIN_CHAT_LOG TWIN_TELEGRAM_ACCOUNTS TWIN_TELEGRAM_API; do
  grep -q "$name" "$MOD" || fail "$MOD has no $name override, so it cannot run in a sandbox"
done

D=$(mktemp -d)
FAKE=
trap '[ -z "$FAKE" ] || kill "$FAKE" 2>/dev/null || true; sudo -n rm -rf "$D"' EXIT
chmod 0755 "$D"
sudo -n install -d -o twin-chat -g twin-chat "$D/home" "$D/home/work" "$D/home/.letta" "$D/home/.letta/mods"
sudo -n install -o twin-chat -g twin-chat -m 644 "$MOD" "$D/home/.letta/mods/twin_mind.ts"
printf '{"accounts":[{"enabled":true,"token":"CONTRACT"}]}\n' | sudo -n -u twin-chat tee "$D/home/accounts.json" >/dev/null

# A fake Telegram Bot API on a free local port. It records each sendMessage call.
: > "$D/posts.jsonl"
python3 - "$D/port" "$D/posts.jsonl" <<'PY' &
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0))).decode()
        with open(sys.argv[2], "a") as handle:
            handle.write(json.dumps({"path": self.path, "body": json.loads(body)}) + "\n")
        out = b'{"ok":true,"result":{"message_id":1}}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    def log_message(self, *args):
        pass
server = HTTPServer(("127.0.0.1", 0), Handler)
with open(sys.argv[1], "w") as handle:
    handle.write(str(server.server_port))
server.serve_forever()
PY
FAKE=$!
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25; do
  [ -s "$D/port" ] && break
  sleep 0.2
done
[ -s "$D/port" ] || fail "the fake Telegram did not start"
PORT=$(cat "$D/port")

PROMPT='<channel-notification source="telegram" chat_id="42" sender_id="42" account_id="contract" sender_name="contract" message_id="1">Contract test. Reply with only the weekday named in your twin-mind-context block. If you have no such block, reply with the single word MISSING.</channel-notification>'
sudo -n -u twin-chat -H env HOME="$D/home" PATH=/opt/node/bin:/usr/local/bin:/usr/bin:/bin \
  DISABLE_AUTOUPDATER=1 DO_NOT_TRACK=1 LETTA_CODE_TELEM=0 \
  TWIN_CHAT_LOG="$D/home/chat-log.jsonl" TWIN_TELEGRAM_ACCOUNTS="$D/home/accounts.json" \
  TWIN_TELEGRAM_API="http://127.0.0.1:$PORT" LETTA="$LETTA" MODEL="$MODEL" PROMPT="$PROMPT" \
  sh -c 'cd "$HOME/work" && set -a && . /run/twin-chat/anthropic.env && set +a && exec timeout 240 "$LETTA" --backend local --new-agent -m "$MODEL" --output-format json --no-skills --no-system-info-reminder -p "$PROMPT"' \
  > "$D/out.json" 2> "$D/err.txt" || fail "Letta did not finish: $(tail -n 3 "$D/err.txt" | tr '\n' ' ')"

sudo -n cat "$D/home/chat-log.jsonl" > "$D/chat-log.jsonl" 2>/dev/null || : > "$D/chat-log.jsonl"
WEEKDAY=$(TZ=Europe/Amsterdam LC_ALL=C date +%A)
python3 - "$D/posts.jsonl" "$D/chat-log.jsonl" "$WEEKDAY" <<'PY'
import json, sys
posts = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
rows = [json.loads(line) for line in open(sys.argv[2]) if line.strip()]
weekday = sys.argv[3]


def fail(why):
    print(f"CHAT CONTRACT: FAIL - {why}")
    sys.exit(1)


if len(posts) != 1:
    fail(f"{len(posts)} messages reached Telegram, expected 1")
body = posts[0]["body"]
if posts[0]["path"] != "/botCONTRACT/sendMessage" or body.get("chat_id") != "42":
    fail(f"the message went to the wrong place: {posts[0]['path']}, chat {body.get('chat_id')}")
if weekday.lower() not in body.get("text", "").lower():
    fail(f"the answer {body.get('text', '')[:80]!r} does not name {weekday}, so the turn-start context did not reach the model")
roles = [(row.get("role"), row.get("via")) for row in rows]
if roles != [("user", None), ("assistant", "relay")]:
    fail(f"the chat log has {roles}, expected the message and its relayed answer")
print(f"CHAT CONTRACT: PASS - the answer ({weekday}) reached Telegram once, and both rows are in the chat log")
PY
