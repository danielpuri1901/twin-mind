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


def _profile_arn():
    if os.environ.get('TWIN_BEDROCK_PROFILE_ARN'):
        return os.environ['TWIN_BEDROCK_PROFILE_ARN']
    try:
        for line in open(os.path.expanduser('~/.hermes/.env')):
            key, _, value = line.strip().partition('=')
            if key == 'TWIN_BEDROCK_PROFILE_ARN' and value:
                return value
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
