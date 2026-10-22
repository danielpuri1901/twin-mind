"""Claude through the Anthropic API, for every Twin call that is not an embedding.

From 2026-10-22 inference runs on Anthropic API credits and AWS credits pay for
infrastructure only. Embeddings stay on Bedrock (Cohere has no Anthropic
equivalent), so the box keeps its bedrock-invoke policy.

The key is the Secrets Manager secret "aws-inference", shared with AgentLab.
It is read at runtime by whoever needs it: the box through its instance role,
the Mac through its AWS session. The environment wins when it is set, so a
local ANTHROPIC_API_KEY or the Hermes gateway (see the anthropic-key plugin)
skips the lookup. Nothing writes the key to disk.
"""
import json
import os
from functools import lru_cache

MODEL = "claude-sonnet-4-6"
SECRET_ID = "aws-inference"
KEY_ENV = "ANTHROPIC_API_KEY"


def _clean(value):
    """Strip the quotes a .env line may carry, as shared/bedrock_profiles.py did."""
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return value.strip()


@lru_cache(maxsize=1)
def api_key():
    """The environment first, then Secrets Manager. The secret may be the bare
    key or a JSON object holding one key; both shapes are handled, as in
    AgentLab."""
    raw = os.environ.get(KEY_ENV, "")
    if not raw.strip():
        import boto3
        raw = boto3.client("secretsmanager", region_name="eu-west-1").get_secret_value(
            SecretId=SECRET_ID)["SecretString"]
    raw = _clean(raw)
    if raw.startswith("{"):
        values = [str(v).strip() for v in json.loads(raw).values()]
        if len(values) != 1:
            raise ValueError(f"{SECRET_ID} as JSON must hold exactly one value")
        raw = values[0]
    if not raw:
        raise ValueError(f"{KEY_ENV} is empty and {SECRET_ID} holds no key")
    return raw


@lru_cache(maxsize=1)
def client():
    import anthropic
    return anthropic.Anthropic(api_key=api_key(), max_retries=3)


def text(model, system, user, *, max_tokens, temperature=0):
    """One text reply, no tools: the shape the recap and the evals used on Bedrock."""
    r = client().messages.create(
        model=model, system=system, messages=[{"role": "user", "content": user}],
        max_tokens=max_tokens, temperature=temperature)
    return "".join(b.text for b in r.content if b.type == "text")
