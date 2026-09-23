#!/usr/bin/env python3
"""Enforced structured output from Bedrock Claude - the project rule in one place.

Deterministic-by-default; when the model MUST return structured data, enforce the shape instead of
prompting-for-JSON-and-regex-parsing. Mechanism (the canonical Claude/Bedrock idiom): define the
shape as a Pydantic model, expose it as a SINGLE tool whose input schema IS that model, and FORCE
the model to call it (`toolChoice`). The model cannot reply in prose - it must produce a tool call
whose `input` conforms to the schema. We then validate with Pydantic (structure + semantic rules),
and on a validation miss we feed the error back and retry (the Instructor pattern) - never silently
default. If it still fails after the retries, we RAISE. A parse failure is loud, not an invisible
`return False` that corrupts a downstream number.

    from shared.structured import structured_call
    class Verdict(BaseModel):
        supported: bool
        reason: str
    v = structured_call(MODEL, system, user, Verdict)   # -> a validated Verdict, or raises
"""
import boto3
from pydantic import BaseModel, ValidationError
from shared.bedrock_profiles import route_model

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

_brt = boto3.client("bedrock-runtime", region_name="eu-west-1")


@traceable(name="structured_call")
def structured_call(model_id, system, user, schema, *, max_tokens=2500, temperature=0, retries=2):
    """Force `model_id` to return an instance of `schema` (a Pydantic BaseModel subclass) via
    forced tool-use, validate it, and return the validated instance. Retries with the validation
    error fed back; raises RuntimeError if it never validates."""
    tool_name = schema.__name__.lower()
    tool = {"toolSpec": {
        "name": tool_name,
        "description": (schema.__doc__ or f"Return a well-formed {schema.__name__}.").strip(),
        "inputSchema": {"json": schema.model_json_schema()},
    }}
    messages = [{"role": "user", "content": [{"text": user}]}]
    last_err = "no attempt"
    for _ in range(retries + 1):
        r = _brt.converse(
            modelId=route_model(model_id), messages=messages, system=[{"text": system}],
            toolConfig={"tools": [tool], "toolChoice": {"tool": {"name": tool_name}}},
            inferenceConfig={"temperature": temperature, "maxTokens": max_tokens})
        blocks = r["output"]["message"]["content"]
        tu = next((b["toolUse"] for b in blocks if "toolUse" in b), None)
        if tu is None:
            last_err = "model returned no toolUse block"
            messages.append({"role": "assistant", "content": blocks})
            messages.append({"role": "user", "content": [{"text": f"You must call the {tool_name} tool. Do it now."}]})
            continue
        try:
            return schema.model_validate(tu["input"])   # structure + any Pydantic validators
        except ValidationError as e:
            last_err = str(e)
            # Bedrock REQUIRES a toolResult immediately after an assistant tool_use. Feed the
            # validation error back AS the tool result (status=error) - that both satisfies the
            # API contract and gives the model the exact feedback (Instructor pattern).
            messages.append({"role": "assistant", "content": blocks})
            messages.append({"role": "user", "content": [{"toolResult": {
                "toolUseId": tu["toolUseId"],
                "content": [{"text": f"Validation failed: {e}. Call {tool_name} again with corrected values."}],
                "status": "error"}}]})
    raise RuntimeError(f"structured_call({schema.__name__}) failed after {retries + 1} tries: {last_err}")
