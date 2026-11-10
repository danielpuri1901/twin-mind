#!/usr/bin/env python3
"""Tell Daniel when a chat message got no answer.

It reads only the chat log (shared/chat_log.py), so it works on any chat harness. A message counts
as unanswered when no assistant row follows it within WAIT seconds. Anything this prints becomes a
Telegram message, because the timer runs it through shared/telegram_send.py --run.

The timer runs every EVERY seconds, and each run looks only at the messages that crossed the WAIT
line since the run before. So each unanswered message is reported once, with no state file.
ponytail: a run that systemd skips or delays past EVERY can miss a message. Add a state file of
reported ids if that ever happens.

It cannot see an answer that was only partly sent. The chat mod covers that case and marks those
rows `via: relay` in the chat log.

    reply_check.py     # prints an alert, or nothing
"""
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared"))
import chat_log  # noqa: E402

WAIT = 300   # seconds a message may wait for an answer
EVERY = 300  # seconds between runs; keep it equal to twin-chat-reply-check.timer


def unanswered(messages, now, wait=WAIT, every=EVERY):
    """User messages that became `wait` seconds old during the last `every` seconds, with no answer after them."""
    late = []
    for index, message in enumerate(messages):
        if message.get("role") != "user" or not wait <= now - message["ts"] < wait + every:
            continue
        if not any(later.get("role") == "assistant" for later in messages[index + 1:]):
            late.append(message)
    return late


def alert(late):
    at = datetime.datetime.fromtimestamp(late[0]["ts"]).strftime("%H:%M")
    return (f"Chat has not answered your message from {at} after {WAIT // 60} minutes. "
            "It may be stuck, or it may wait for your approval. Send the message again. "
            "If that does not help, check twin-chat on the box.")


if __name__ == "__main__":
    waiting = unanswered(chat_log.read(), time.time())
    if waiting:
        print(alert(waiting))
