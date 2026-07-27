"""langsmith-trace - Hermes plugin that traces conversations to LangSmith.

First-party (we own it), the LangSmith counterpart to Hermes's bundled Langfuse plugin. It emits
via the langsmith SDK's ``RunTree`` - already installed in the hermes venv for the morning brief -
so the Twin's conversations land in the SAME LangSmith project, threaded, as the brief.

Model: ONE root run per conversation turn (``hermes.turn``), opened on ``pre_llm_call`` and closed
on ``post_llm_call``; each tool call is a nested child (``pre_tool_call`` / ``post_tool_call``).
Every turn of one Hermes session shares ``thread_id = session_id``, so LangSmith groups them into a
single thread. (Per-LLM-call token/cost children via ``pre_api_request`` / ``post_api_request`` are
a deliberate v2 - kept out of v1 to minimise surface area on the live agent.)

FAIL-OPEN is the hard rule: a missing SDK, a missing ``LANGSMITH_API_KEY``, or ANY exception in a
hook becomes a silent no-op. The agent loop is never impacted.

Env:
  LANGSMITH_API_KEY          - required; without it every hook no-ops
  LANGSMITH_ENDPOINT         - LangSmith API (box: https://eu.api.smith.langchain.com)
  LANGSMITH_PROJECT          - project for chat traces (default: twin-mind)
  LANGSMITH_TRACE_MAX_CHARS  - per-field truncation (default: 12000)

Note: RunTree.post() sends to LangSmith whenever LANGSMITH_API_KEY is set - it is NOT gated by
LANGSMITH_TRACING (that flag only controls @traceable / the trace context manager).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    from langsmith.run_trees import RunTree
except Exception:  # fail-open when the optional SDK is absent
    RunTree = None

_PROJECT = os.environ.get("LANGSMITH_PROJECT") or "twin-mind"
try:
    _MAX_CHARS = int(os.environ.get("LANGSMITH_TRACE_MAX_CHARS") or "12000")
except ValueError:
    _MAX_CHARS = 12000
_MAX_OPEN_TURNS = 256  # leak guard: turns interrupted before post_llm_call never close on their own

_LOCK = threading.Lock()
_TURNS: "Dict[str, TurnState]" = {}
_ENABLED: Optional[bool] = None


@dataclass
class TurnState:
    root: Any
    tools: Dict[str, Any] = field(default_factory=dict)      # tool_call_id -> child RunTree
    pending: Dict[str, list] = field(default_factory=dict)   # tool_name -> [child] when no id given
    last_updated: float = field(default_factory=time.time)


def _enabled() -> bool:
    """SDK present AND an API key set. Cache only the POSITIVE result - never cache a negative,
    because the plugin may import before Hermes loads ~/.hermes/.env into os.environ; a cached
    False would leave it inert forever even once the key appears. Re-checking is one dict lookup."""
    global _ENABLED
    if _ENABLED:
        return True
    if RunTree is None:
        return False
    if os.environ.get("LANGSMITH_API_KEY"):
        _ENABLED = True
        return True
    return False


def _safe(value: Any) -> Any:
    """Stringify + truncate any value so a huge tool result can never bloat a trace."""
    try:
        if value is None:
            return None
        s = value if isinstance(value, str) else str(value)
        if len(s) > _MAX_CHARS:
            return s[:_MAX_CHARS] + f"... [+{len(s) - _MAX_CHARS} chars]"
        return s
    except Exception:
        return "<unserializable>"


def _scope(task_id: str, session_id: str) -> str:
    if task_id:
        return f"task:{task_id}"
    if session_id:
        return f"session:{session_id}"
    return f"thread:{threading.get_ident()}"


def _key(task_id: str, session_id: str, turn_id: str = "", api_request_id: str = "") -> str:
    """Stable per-turn scope key. turn_id preferred so pre_llm_call and post_llm_call (both carry
    turn_id) resolve to the same root; falls back to api_request_id, then task/session."""
    if turn_id:
        return f"{_scope(task_id, session_id)}:turn:{turn_id}"
    if api_request_id:
        return f"{_scope(task_id, session_id)}:api:{api_request_id}"
    return _scope(task_id, session_id)


def _evict_locked() -> None:
    """Caller holds _LOCK. Bound the leak from turns that never reach post_llm_call by ending the
    oldest open roots. Evict down to _MAX_OPEN_TURNS - 1 so the about-to-be-added entry is the cap."""
    over = len(_TURNS) - (_MAX_OPEN_TURNS - 1)
    if over <= 0:
        return
    for key, st in sorted(_TURNS.items(), key=lambda kv: kv[1].last_updated)[:over]:
        _TURNS.pop(key, None)
        try:
            st.root.end(outputs={"note": "evicted: turn never reported completion"})
            st.root.patch()
        except Exception:
            pass


# ---- hooks ------------------------------------------------------------------

def on_pre_llm_call(*, task_id: str = "", session_id: str = "", user_message: Any = None,
                    conversation_history: Any = None, model: str = "", platform: str = "",
                    is_first_turn: bool = False, turn_id: str = "", api_request_id: str = "",
                    **_: Any) -> None:
    """Fires once per turn, before the tool-calling loop. Open the root run."""
    if not _enabled():
        return
    try:
        key = _key(task_id, session_id, turn_id, api_request_id)
        with _LOCK:
            existing = _TURNS.get(key)
            if existing is not None:                       # get-or-create: never double-open a turn
                existing.last_updated = time.time()
                return
            root = RunTree(
                name="hermes.turn",
                run_type="chain",
                inputs={"user_message": _safe(user_message)},
                project_name=_PROJECT,
                tags=["agent:chat", "env:prod", f"platform:{platform or 'cli'}"],
                extra={"metadata": {
                    "thread_id": session_id or task_id or "sessionless",  # LangSmith thread grouping
                    "session_id": session_id,
                    "model": model,
                    "platform": platform,
                    "is_first_turn": is_first_turn,
                    "source": "hermes",
                }},
            )
            root.post()
            _evict_locked()
            _TURNS[key] = TurnState(root=root)
    except Exception as exc:  # fail-open
        logger.debug("langsmith-trace pre_llm_call failed: %s", exc)


def on_pre_tool_call(*, tool_name: str = "", args: Any = None, task_id: str = "",
                     session_id: str = "", tool_call_id: str = "",
                     turn_id: str = "", api_request_id: str = "", **_: Any) -> None:
    """Open a nested child run for a tool call under the current turn."""
    if not _enabled():
        return
    try:
        key = _key(task_id, session_id, turn_id, api_request_id)
        with _LOCK:
            st = _TURNS.get(key)
            if st is None:
                return
            child = st.root.create_child(
                name=f"tool:{tool_name}",
                run_type="tool",
                inputs={"args": _safe(args)},
            )
            child.post()
            if tool_call_id:
                st.tools[tool_call_id] = child
            else:
                st.pending.setdefault(tool_name, []).append(child)
            st.last_updated = time.time()
    except Exception as exc:  # fail-open
        logger.debug("langsmith-trace pre_tool_call failed: %s", exc)


def on_post_tool_call(*, tool_name: str = "", args: Any = None, result: Any = None,
                      task_id: str = "", session_id: str = "", tool_call_id: str = "",
                      duration_ms: int = 0, turn_id: str = "", api_request_id: str = "",
                      **_: Any) -> None:
    """Close the tool's child run with its result."""
    if not _enabled():
        return
    try:
        key = _key(task_id, session_id, turn_id, api_request_id)
        child = None
        with _LOCK:
            st = _TURNS.get(key)
            if st is None:
                return
            if tool_call_id:
                child = st.tools.pop(tool_call_id, None)
            if child is None:
                queue = st.pending.get(tool_name)
                if queue:
                    child = queue.pop(0)
            st.last_updated = time.time()
        if child is not None:
            meta = {"duration_ms": duration_ms} if duration_ms else None
            child.end(outputs={"result": _safe(result)}, metadata=meta)
            child.patch()
    except Exception as exc:  # fail-open
        logger.debug("langsmith-trace post_tool_call failed: %s", exc)


def on_post_llm_call(*, task_id: str = "", session_id: str = "", assistant_response: Any = None,
                     model: str = "", platform: str = "", turn_id: str = "",
                     api_request_id: str = "", **_: Any) -> None:
    """Fires once per turn, after the tool loop (successful turns only). Close the root run."""
    if not _enabled():
        return
    try:
        key = _key(task_id, session_id, turn_id, api_request_id)
        with _LOCK:
            st = _TURNS.pop(key, None)
        if st is None:
            return
        # close any tool child that never received a post_tool_call, so nothing dangles
        stragglers = list(st.tools.values()) + [c for q in st.pending.values() for c in q]
        for child in stragglers:
            try:
                child.end(outputs={"note": "tool did not report completion"})
                child.patch()
            except Exception:
                pass
        st.root.end(outputs={"assistant_response": _safe(assistant_response)})
        st.root.patch()
        # Flush now: a one-off `hermes chat -q` or a scheduled run may exit before the SDK's
        # background thread posts the trace, silently dropping it. Long-lived sessions just re-flush.
        try:
            st.root.client.flush()
        except Exception:
            pass
    except Exception as exc:  # fail-open
        logger.debug("langsmith-trace post_llm_call failed: %s", exc)


def register(ctx) -> None:
    """Hermes calls this once at startup to wire the hooks."""
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("post_llm_call", on_post_llm_call)
    logger.debug("langsmith-trace registered (project=%s)", _PROJECT)
