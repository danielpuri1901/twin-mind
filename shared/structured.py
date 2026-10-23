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
"""
import anthropic
from pydantic import BaseModel, ValidationError
from shared.claude import client, sampling

try:
    from langsmith import traceable, tracing_context
except ImportError:  # tracing is optional; a missing lib must never break a live agent
    from contextlib import contextmanager

    def traceable(*d_args, **d_kwargs):
        if len(d_args) == 1 and callable(d_args[0]) and not d_kwargs:
            return d_args[0]

        def _decorator(fn):
            return fn
        return _decorator

    @contextmanager
    def tracing_context(**_kwargs):
        yield


@traceable(name="structured_call")
def structured_call(model_id, system, user, schema, *, max_tokens=2500, temperature=None, retries=2):
    """Make `model_id` return an instance of `schema` (a Pydantic BaseModel subclass) through
    structured outputs, validate it, and return the validated instance. Retries with the validation
    error fed back; raises RuntimeError if it never validates."""
    fmt = {"type": "json_schema", "schema": anthropic.transform_schema(schema)}
    messages = [{"role": "user", "content": user}]
    last_err = "no attempt"
    for _ in range(retries + 1):
        r = client().messages.create(
            model=model_id, system=system, messages=messages,
            output_config={"format": fmt}, max_tokens=max_tokens, **sampling(temperature))
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
