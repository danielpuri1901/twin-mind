"""Route Twin chat, brief, recap, and eval calls for project cost attribution.

Keep the logical Claude model ID inside Hermes so provider detection, context
limits, prompt caching, and streaming stay unchanged. Replace only the model
passed to the final Bedrock SDK call.

The profile ARN is private (it names the AWS account), so it lives in
TWIN_BEDROCK_PROFILE_ARN: the process environment first, then ~/.hermes/.env.
Unset means no routing: calls go to the plain model ID and still work.
"""
import os
from functools import wraps

MODEL = 'eu.anthropic.claude-sonnet-4-6'


def _clean(value):
    """Strip the quotes a .env line may carry.

    systemd strips matching quotes when it loads an EnvironmentFile, so the
    gateway always saw a clean ARN and this went unnoticed. A script reading
    the same file directly did not, and handed Bedrock an ARN wrapped in
    apostrophes, which fails as "The provided model identifier is invalid" -
    an error that names the model and says nothing about quoting. Every other
    env loader in this repo already strips them; this one did not.
    """
    value = (value or '').strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return value.strip()


def _profile_arn():
    if os.environ.get('TWIN_BEDROCK_PROFILE_ARN'):
        return _clean(os.environ['TWIN_BEDROCK_PROFILE_ARN']) or None
    try:
        for line in open(os.path.expanduser('~/.hermes/.env')):
            key, _, value = line.strip().partition('=')
            if key == 'TWIN_BEDROCK_PROFILE_ARN':
                cleaned = _clean(value)
                if cleaned:
                    return cleaned
    except OSError:
        pass
    return None


PROFILE = _profile_arn()


def route_model(model):
    return PROFILE if PROFILE and model == MODEL else model


def wrap_anthropic_call(call):
    @wraps(call)
    def routed(client, api_kwargs, **kwargs):
        from anthropic import AnthropicBedrock
        if isinstance(client, AnthropicBedrock):
            api_kwargs = dict(api_kwargs, model=route_model(api_kwargs['model']))
        return call(client, api_kwargs, **kwargs)
    return routed
