#!/usr/bin/env python3
"""Enforced structured output from Claude - the project rule in one place.

Deterministic-by-default; when the model MUST return structured data, enforce the shape instead of
prompting-for-JSON-and-regex-parsing. Mechanism (structured outputs): define the shape as a Pydantic
model and send its JSON schema as the response format (`output_config.format`). The API constrains
the reply to that schema, so the model cannot answer in prose. We then validate with Pydantic
(structure + semantic rules), and on a validation miss we feed the error back and retry (the
Instructor pattern) - never silently default. If it still fails after the retries, we RAISE. A parse
failure is loud, not an invisible `return False` that corrupts a downstream number.

    from shared.structured import structured_call
    class Verdict(BaseModel):
        supported: bool
        reason: str
    v = structured_call(MODEL, system, user, Verdict)   # -> a validated Verdict, or raises

History: Bedrock Converse forced tool use until 2026-10-22, Messages API forced tool use for one
day, structured outputs since 2026-10-23: Sonnet 5.5 rejects `tool_choice` of type `tool` or `any`
("not supported for this model"), and structured outputs work on Sonnet 4.6 (the eval judges) too.
`temperature` is sent only when the caller sets it; Sonnet 5.5 rejects the parameter.

Thinking counts against max_tokens on Sonnet 5.5, so a small budget can end with no text at all
(the 2026-11-06 ship gate: 500 tokens, one thinking block, no answer). MIN_MAX_TOKENS is a floor
for every caller. It costs nothing unless the model uses it.

Tracing goes to Langfuse (LangSmith removed 2026-10-28). Each call is a Langfuse generation with
its model and token usage, so evals/costs.py prices the brief, not only chat.
"""
import os

import anthropic
from pydantic import BaseModel, ValidationError
from shared.claude import client, sampling

MIN_MAX_TOKENS = 4000

# The box names the Langfuse keys for the Hermes plugin; the SDK reads the plain names.
for _name in ("PUBLIC_KEY", "SECRET_KEY", "BASE_URL"):
    if os.environ.get(f"HERMES_LANGFUSE_{_name}"):
        os.environ.setdefault(f"LANGFUSE_{_name}", os.environ[f"HERMES_LANGFUSE_{_name}"])

try:
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        raise ImportError("no Langfuse keys")  # trace nothing and log nothing, e.g. the Mac ship gate
    from langfuse import get_client, observe, propagate_attributes
except ImportError:  # tracing is optional; a missing lib must never break a live agent
    from contextlib import contextmanager

    get_client = None

    def observe(*d_args, **d_kwargs):
        if len(d_args) == 1 and callable(d_args[0]) and not d_kwargs:
            return d_args[0]

        def _decorator(fn):
            return fn
        return _decorator

    @contextmanager
    def propagate_attributes(**_kwargs):
        yield


def _record_usage(model_id, usage):
    """Put the model and summed token usage on the current Langfuse generation. Fail-open."""
    if get_client is None:
        return
    try:
        get_client().update_current_generation(model=model_id, usage_details=usage)
    except Exception:
        pass


@observe(name="structured_call", as_type="generation")
def structured_call(model_id, system, user, schema, *, max_tokens=2500, temperature=None, retries=2):
    """Make `model_id` return an instance of `schema` (a Pydantic BaseModel subclass) through
    structured outputs, validate it, and return the validated instance. Retries with the validation
    error fed back; raises RuntimeError if it never validates."""
    fmt = {"type": "json_schema", "schema": anthropic.transform_schema(schema)}
    messages = [{"role": "user", "content": user}]
    last_err = "no attempt"
    usage = {"input": 0, "output": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    for _ in range(retries + 1):
        r = client().messages.create(
            model=model_id, system=system, messages=messages,
            output_config={"format": fmt}, max_tokens=max(max_tokens, MIN_MAX_TOKENS), **sampling(temperature))
        usage["input"] += r.usage.input_tokens
        usage["output"] += r.usage.output_tokens
        usage["cache_read_input_tokens"] += r.usage.cache_read_input_tokens or 0
        usage["cache_creation_input_tokens"] += r.usage.cache_creation_input_tokens or 0
        _record_usage(model_id, usage)
        text = "".join(b.text for b in r.content if b.type == "text")
        if not text.strip():   # a budget or refusal stop; the same request again would not help
            raise RuntimeError(f"structured_call({schema.__name__}): no text, stop_reason={r.stop_reason}, "
                               f"blocks={[b.type for b in r.content]}, max_tokens={max_tokens}")
        try:
            return schema.model_validate_json(text)   # structure + any Pydantic validators
        except ValidationError as e:
            last_err = str(e)
            # Feed the exact validation error back as the next user turn (Instructor pattern).
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content":
                             f"Validation failed: {e}. Return a corrected {schema.__name__}."})
    raise RuntimeError(f"structured_call({schema.__name__}) failed after {retries + 1} tries: {last_err}")
