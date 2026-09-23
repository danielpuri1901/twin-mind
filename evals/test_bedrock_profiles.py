"""Protect Claude detection, streaming, and cache markers during cost routing."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['TWIN_BEDROCK_PROFILE_ARN'] = 'arn:aws:bedrock:eu-west-1:111122223333:application-inference-profile/example'

class ProfileTests(unittest.TestCase):
    def test_route_only_known_model(self):
        from shared.bedrock_profiles import route_model, MODEL, PROFILE
        self.assertEqual(route_model(MODEL), PROFILE)
        self.assertEqual(route_model('other-model'), 'other-model')
        self.assertEqual(route_model(PROFILE), PROFILE)

    def test_unset_profile_means_no_routing(self):
        import shared.bedrock_profiles as bp
        with patch.object(bp, 'PROFILE', None):
            self.assertEqual(bp.route_model(bp.MODEL), bp.MODEL)

    def test_stream_and_cache_unchanged(self):
        from shared.bedrock_profiles import wrap_anthropic_call, MODEL, PROFILE
        original = {'model': MODEL, 'system': [{'type': 'text', 'text': 'prefix', 'cache_control': {'type': 'ephemeral'}}]}
        calls = []
        def invoke(client, arguments, **kwargs):
            calls.append((arguments, kwargs))
            return 'response'
        class Bedrock: pass
        with patch('anthropic.AnthropicBedrock', Bedrock):
            wrapped = wrap_anthropic_call(invoke)
            for streaming in (True, False):
                self.assertEqual(wrapped(Bedrock(), original, prefer_stream=streaming), 'response')
                self.assertEqual(calls[-1][0]['model'], PROFILE)
                self.assertIs(calls[-1][0]['system'], original['system'])
                self.assertEqual(calls[-1][1]['prefer_stream'], streaming)
            wrapped(object(), original)
        self.assertEqual(calls[-1][0]['model'], MODEL)
        self.assertEqual(original['model'], MODEL)

if __name__ == '__main__': unittest.main()
