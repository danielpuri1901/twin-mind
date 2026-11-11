"""The chat agent's messages, as the twin_mind mod records them.

One JSON object per line: {ts, role, text, conversation_id}, where role is user or assistant.
An assistant row that the mod sent itself, because the model left it as plain text, also has
via: "relay". Count them with: grep -c '"via":"relay"' /var/lib/twin-chat/chat-log.jsonl
This is the only contract the corpus ingest and the weekly recap have with the chat harness, so
swapping the harness means changing the writer and nothing else. Nothing here depends on Letta.

The file is append-only, so a message's line number is a stable id. Ids start at FIRST_ID so they
can share the ingest ledger with the Hermes row ids that came before.
"""
import json
import os
import sys

CHAT_LOG = os.environ.get("TWIN_CHAT_LOG", "/var/lib/twin-chat/chat-log.jsonl")
FIRST_ID = 10_000_000_000


def read(path=None):
    """Every well-formed message, oldest first, each with its stable `id`. No log yet means no messages."""
    messages = []
    try:
        with open(path or CHAT_LOG, encoding="utf-8") as handle:
            for number, line in enumerate(handle):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    print(f"chat log line {number} is not JSON; skipped", file=sys.stderr)
                    continue
                messages.append({**row, "id": FIRST_ID + number})
    except FileNotFoundError:
        pass
    return messages
