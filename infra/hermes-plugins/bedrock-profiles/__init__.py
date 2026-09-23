"""Apply cost routing after Hermes has selected its Claude SDK path."""
import sys
from pathlib import Path


def register(ctx):
    root = Path.home() / 'super-project'
    if not root.is_dir():
        root = Path.home() / 'Super Project'
    sys.path.insert(0, str(root))
    from agent import anthropic_adapter
    from shared.bedrock_profiles import wrap_anthropic_call
    call = anthropic_adapter.create_anthropic_message
    if not getattr(call, '_twin_profile_routing', False):
        routed = wrap_anthropic_call(call)
        routed._twin_profile_routing = True
        anthropic_adapter.create_anthropic_message = routed
