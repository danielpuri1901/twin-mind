#!/usr/bin/env python3
"""Chat-alive rule and chat Langfuse traces (2026-11-06). Deterministic, free, no network:
a fake langfuse module stands in for the SDK."""
import contextlib
import io
import os
import sys
import types

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "infra", "bin"))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import chat_alive
import ingest_twin_chat as I

# chat-alive: both the service and the gateway process, or nothing
gw = ["/opt/letta/bin/python /opt/letta/bin/letta channel-gateway --telegram"]
assert chat_alive.is_up(True, ["bash"] + gw)
assert not chat_alive.is_up(False, gw)
assert not chat_alive.is_up(True, ["bash", "letta server"])

# pairing: user then assistant only
recs = [{"who": w, "text": t} for w, t in
        [("twin", "orphan"), ("me", "q1"), ("twin", "a1"), ("me", "q2"), ("me", "q3"), ("twin", "a3")]]
assert I.chat_pairs(recs) == [("q1", "a1"), ("q3", "a3")]

# fake SDK
calls = []


class FakeClient:
    def start_as_current_observation(self, **kw):
        calls.append(("span", kw)); return contextlib.nullcontext()

    def set_current_trace_io(self, **kw):
        calls.append(("io", kw))

    def flush(self):
        calls.append(("flush",))


fake = types.ModuleType("langfuse")
fake.get_client = FakeClient
fake.propagate_attributes = lambda **kw: (calls.append(("attrs", kw)), contextlib.nullcontext())[1]
sys.modules["langfuse"] = fake


def run(keys):
    calls.clear()
    I.telegram_send.env = lambda k: keys.get(k, "")
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        I.send_traces(recs)
    return err.getvalue()


assert run({}) == "" and not calls                       # no keys: silent no-op
keys = {"HERMES_LANGFUSE_PUBLIC_KEY": "pk", "HERMES_LANGFUSE_SECRET_KEY": "sk"}
assert run(keys) == ""
attrs = [c[1] for c in calls if c[0] == "attrs"]
assert len(attrs) == 2 and attrs[0] == {"session_id": "chat", "tags": ["agent:chat", "env:prod"]}
assert [c[1]["input"] for c in calls if c[0] == "span"] == ["q1", "q3"]
assert calls[-1] == ("flush",)                           # flushed before exit

FakeClient.start_as_current_observation = lambda self, **kw: 1 / 0
e = run(keys)                                            # failure: one stderr line, no raise, still flushed
assert e.count("\n") == 1 and "langfuse" in e and calls[-1] == ("flush",), e
print("chat observability: ok")
