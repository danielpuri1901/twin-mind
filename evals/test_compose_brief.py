#!/usr/bin/env python3
"""Focused checks for project-bound technical brief composition."""
import contextlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "agents" / "brief" / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

structured = types.ModuleType("shared.structured")
structured.structured_call = lambda *args, **kwargs: None
structured.traceable = lambda *args, **kwargs: lambda function: function
structured.tracing_context = lambda **kwargs: contextlib.nullcontext()
sys.modules["shared.structured"] = structured

import compose_brief as compose
from project_activity import ActivityCluster


def cluster(cluster_id: str = "real", project: str = "agentlab") -> ActivityCluster:
    return ActivityCluster(
        cluster_id=cluster_id,
        project=project,
        repo_id="repo",
        event_ids=("commit",),
        latest_time=1,
        subjects=("feat: guarded story generation",),
        paths=("worker.py",),
        score=10,
        candidate_text="Project: agentlab\nChanges: guarded story generation\nFiles: worker.py",
    )


def brief(source_id: str = "real", project: str = "agentlab") -> compose.Brief:
    return compose.Brief(
        needs_you_today=[],
        ai_advancements=["one"],
        technical_thing=compose.TechnicalThing(
            source_id=source_id,
            project=project,
            topic="bounded retries",
            concept="A bounded retry limits repeated attempts after a failure.",
            quiz="Why bound retries?",
            answer="To cap delay and cost.",
        ),
        coach="Keep the failure contract explicit.",
    )


class ComposeBriefTests(unittest.TestCase):
    def test_prompt_uses_project_candidates_instead_of_the_stale_changelog(self):
        facts = {
            "date_line": "Sunday, 6 September 2026",
            "covered": "(none)",
            "ai_news": "(none)",
            "technical_candidates": [cluster()],
            "reviewed_count": 0,
            "inbox_text": "(none)",
            "weather": "Luxembourg: 20°C",
            "calendar_lines": ["(no events)"],
        }

        prompt = compose.build_user(facts)

        self.assertIn("TECHNICAL CANDIDATES", prompt)
        self.assertIn("agentlab", prompt)
        self.assertNotIn("TOP CHANGELOG ENTRY", prompt)

    def test_source_must_match_the_visible_shortlist(self):
        self.assertEqual(compose.validate_technical_source(brief(), [cluster()]), cluster())
        self.assertIsNone(compose.validate_technical_source(brief("invented"), [cluster()]))
        self.assertIsNone(compose.validate_technical_source(brief(project="other"), [cluster()]))

    def test_post_compose_repeat_is_omitted_without_another_model_call(self):
        made = brief()
        with mock.patch.object(compose, "compose", return_value=made) as model_call:
            with mock.patch.object(compose, "filter_novel_with_vectors", return_value=[]):
                result, selected, status, semantic, vector = compose.compose_with_technical_gate({"technical_candidates": [cluster()]})

        self.assertIsNone(result.technical_thing)
        self.assertEqual(selected, cluster())
        self.assertEqual(status, "rejected_repeat")
        self.assertIn("bounded retries", semantic)
        self.assertIsNone(vector)
        model_call.assert_called_once()

    def test_render_omits_optional_technical_section(self):
        made = brief()
        made.technical_thing = None
        facts = {
            "weather": "Luxembourg: 20°C",
            "calendar_lines": ["(no events)"],
            "reviewed_line": "Reviewed 0 messages since today",
        }

        rendered = compose.render(made, facts)

        self.assertNotIn("ONE TECHNICAL THING", rendered)
        self.assertIn("COACH", rendered)

    def test_send_failure_records_no_novelty_or_event_state(self):
        send_error = compose.subprocess.CalledProcessError(1, ["send_email.py"])
        with mock.patch.object(compose.subprocess, "run", side_effect=send_error):
            with mock.patch.object(compose, "record_seen") as record_seen:
                with mock.patch.object(compose.PA, "record_handled") as record_handled:
                    with self.assertRaises(compose.subprocess.CalledProcessError):
                        compose.deliver("subject", "body", brief(), cluster(), "delivered", "semantic", [0.0, 1.0])

        record_seen.assert_not_called()
        record_handled.assert_not_called()

    def test_success_records_delivered_concept_and_exact_events(self):
        made = brief()
        with mock.patch.object(compose.subprocess, "run") as send:
            with mock.patch.object(compose, "record_seen") as record_seen:
                with mock.patch.object(compose.PA, "record_handled") as record_handled:
                    compose.deliver("subject", "body", made, cluster(), "delivered", "semantic", [0.0, 1.0])

        self.assertTrue(send.call_args.kwargs["check"])
        record_seen.assert_any_call(
            ["semantic"],
            store=compose.PA.NOVELTY_STORE,
            vectors=[[0.0, 1.0]],
            fail_silently=False,
        )
        record_seen.assert_any_call(made.ai_advancements)
        record_handled.assert_called_once_with(cluster(), "delivered")


if __name__ == "__main__":
    unittest.main(verbosity=2)
