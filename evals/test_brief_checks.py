#!/usr/bin/env python3
"""Tests for evals/brief_checks.py - the deterministic brief checks.

Runnable two ways: `python3 -m pytest evals/test_brief_checks.py -v`, or plain
`python3 evals/test_brief_checks.py` (the __main__ block runs them without pytest).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brief_checks as BC


def _good_brief():
    return {
        "needs_you_today": [{"who": "Palantir", "what": "branch deletion", "why_now": "today"}],
        "ai_advancements": ["inference compute is a capability dial", "long context is not retrieval"],
        "technical_thing": {
            "source_id": "cluster-1", "project": "agentlab",
            "topic": "forced tool use", "concept": "force the shape, do not ask for it",
            "quiz": "why force?", "answer": "so it cannot reply in prose",
        },
        "coach": "name the owner and the alarm in the same commit",
    }


def _rendered(headers=BC.SECTION_HEADERS):
    div = "=" * 10
    lines = []
    for h in headers:
        lines += [div, h, div, "body line", ""]
    return "\n".join(lines)


def test_sections_present_pass():
    assert BC.sections_present(_good_brief()).passed


def test_sections_present_fail_empty_coach():
    b = _good_brief(); b["coach"] = "  "
    r = BC.sections_present(b)
    assert not r.passed and "coach" in r.detail


def test_sections_present_fail_missing_technical_field():
    b = _good_brief(); b["technical_thing"]["source_id"] = ""
    r = BC.sections_present(b)
    assert not r.passed and "source_id" in r.detail


def test_sections_present_allows_no_fresh_technical_item():
    b = _good_brief(); b["technical_thing"] = None
    assert BC.sections_present(b).passed


def test_format_ok_pass():
    assert BC.format_ok(_rendered()).passed


def test_format_ok_pass_without_optional_technical_section():
    headers = [h for h in BC.SECTION_HEADERS if h != "ONE TECHNICAL THING"]
    assert BC.format_ok(_rendered(headers)).passed


def test_format_ok_today_not_matched_inside_needs_you_today():
    # "TODAY" as a standalone header must be found on its own line, not inside "NEEDS YOU TODAY"
    assert BC.format_ok(_rendered()).passed


def test_format_ok_fail_missing_header():
    r = BC.format_ok(_rendered([h for h in BC.SECTION_HEADERS if h != "COACH"]))
    assert not r.passed and "COACH" in r.detail


def test_format_ok_fail_out_of_order():
    swapped = ["AI ADVANCEMENTS", "NEEDS YOU TODAY", "TODAY", "ONE TECHNICAL THING", "COACH"]
    assert not BC.format_ok(_rendered(swapped)).passed


def test_date_matches_pass():
    assert BC.date_matches("Morning brief - Friday 24 July", "Friday 24 July").passed


def test_date_matches_fail():
    r = BC.date_matches("Morning brief - Friday 25 July", "Friday 24 July")
    assert not r.passed


def test_no_em_dash_pass():
    assert BC.no_em_dash(_good_brief()).passed


def test_no_em_dash_fail():
    b = _good_brief(); b["coach"] = "do the thing — now"
    assert not BC.no_em_dash(b).passed


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}  {e}")
        except Exception as e:
            print(f"ERROR {t.__name__}  {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
