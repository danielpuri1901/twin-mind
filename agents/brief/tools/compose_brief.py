#!/usr/bin/env python3
"""Morning brief - the PROD-READY pipeline (reference implementation for the whole system).

Deterministic-by-default. The brief used to be an autonomous agent that composed + assembled +
sent, which is why it hit cron approval-gates and guessed the date. This replaces it with a
straight-line pipeline and exactly ONE constrained LLM call:

    gather_facts()   deterministic - weather, calendar, state-annotated inbox, counts, date,
                     covered-topics, and novel project-activity candidates
        |            all facts in the prompt
    compose()        the ONE LLM step - Bedrock forced tool-use -> a validated `Brief` (SECTION
                     CONTENT only); the model cannot reply in prose and cannot invent structure
        |
    render()         deterministic - subject+date, section dividers, weather/calendar TODAY block,
                     the "Reviewed N" line: all assembled by code, impossible to malform
        |
    send_email.py    deterministic, recipient-locked

Result: format/date/counts are code-guaranteed, there is no autonomous agent so there are no
approval-gates, and the only thing left to EVALUATE is the quality of the content (one calibrated
grader). Run with --dry-run to compose + print without sending.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # tools->brief->agents->super-project
sys.path.insert(0, HERE)                                # prefetch
sys.path.insert(0, REPO)                                # shared.structured
import prefetch as PF
import project_activity as PA
from shared.novelty import filter_novel_with_vectors, record as record_seen
from shared.structured import structured_call, traceable, tracing_context
from pydantic import BaseModel

MODEL = "eu.anthropic.claude-sonnet-4-6"
DIV = "━" * 29   # the section divider the format contract requires
SEND_EMAIL = os.path.join(HERE, "send_email.py")
FIXTURE_DIR = os.path.expanduser("~/twin-corpus/datasets/brief-inputs")


# ---------- the schema the model is FORCED to fill (section CONTENT only) ----------

class NeedsItem(BaseModel):
    who: str        # the person / source
    what: str       # what it is, one line
    why_now: str    # why it needs Daniel today


class TechnicalThing(BaseModel):
    source_id: str     # exact cluster ID from the visible shortlist
    project: str       # exact project name from the visible shortlist
    topic: str         # 2-4 word label for dedup, e.g. "prompt caching" - never taught twice
    concept: str       # 3-4 sentences teaching the concept
    quiz: str          # one question
    answer: str        # its answer


class Brief(BaseModel):
    """Daniel's morning brief - SECTION CONTENT ONLY. The format, subject, date, message-count line,
    and the TODAY block (weather + calendar) are rendered deterministically by code, never here."""
    needs_you_today: list[NeedsItem]   # section 1; empty list if nothing needs a decision
    ai_advancements: list[str]         # section 3; 2-3 insight items, none on the covered list
    technical_thing: Optional[TechnicalThing]  # absent when no fresh technical lesson survives
    coach: str                         # section 5; one grounded nudge


# ---------- deterministic facts (reuse prefetch.py's building blocks) ----------

def gather_facts():
    now = datetime.now(PF.LUX)
    cal = subprocess.run(["python3", os.path.join(HERE, "calendar_read.py"), "--days", "1"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    inbox_text, n = PF.inbox()
    try:
        cursor = open(os.path.expanduser("~/.hermes/state/last_brief_sent")).read().strip()[:16]
    except Exception:
        cursor = "the last 24h"
    try:
        covered = open(os.path.expanduser("~/.hermes/state/digest-covered.txt")).read().strip()
    except Exception:
        covered = "(none yet)"
    technical_candidates = PA.shortlist() if PA.ensure_technical_history() else []
    return {
        "date_subject": f"{now.strftime('%A')} {now.day} {now.strftime('%B')}",
        "date_line": f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y')} (Europe/Luxembourg)",
        "weather": PF.weather(),
        "calendar_lines": cal.splitlines() if cal else ["(no events)"],
        "inbox_text": inbox_text,
        "reviewed_count": n,
        "reviewed_line": f"Reviewed {n} messages since {cursor}",
        "covered": covered,
        "technical_candidates": technical_candidates,
        "ai_news": PF.ai_news(),
    }


# ---------- the one LLM step ----------

SYS = (
    "You compose the CONTENT of Daniel's morning brief. All facts are already gathered and given to "
    "you - judge and write, never invent or re-fetch. Return the four content sections via the tool; "
    "the format, subject, date, counts, and the weather/calendar TODAY block are handled by code, so "
    "do NOT produce them.\n"
    "- needs_you_today: judge which inbox items need a DECISION from Daniel today. Every item now carries "
    "a body snippet - READ IT; the subject alone hides the real ask (an interview take-home, a recruiter "
    "reply that looks like a stale calendar invite). The inbox is now UNFILTERED, so obvious "
    "marketing/newsletters appear - do NOT surface those. Flags are facts: REPLIED-ALREADY means the ball "
    "left his court (skip); anything Gmail marked STARRED or IMPORTANT surfaces unless the body is clearly "
    "stale; an UNREAD email from a real person, a question, a deadline, or money surfaces; newest evidence "
    "wins. Empty list if nothing needs him. No ready-to-send drafts.\n"
    "- ai_advancements: 2-3 INSIGHT items drawn ONLY from the RECENT AI NEWS block. Pick the most "
    "substantive advances (model releases, research results, real developer tools) and IGNORE stock, "
    "marketing, funding, or off-topic items. Do NOT use anything outside the block, and NEVER invent a "
    "statistic, benchmark number, or lab measurement. Turn each into one insight (not a headline) and cite "
    "its source name + date. Skip anything on the covered-topics list. If nothing in the block is a real "
    "advance, return an empty list. Tie to Daniel's work only when natural.\n"
    "- technical_thing: use ONLY the TECHNICAL CANDIDATES block. Choose the most useful transferable "
    "technical lesson; use system impact as the tiebreaker. Prefer architecture, reliability, security, "
    "data integrity, and reusable engineering mechanisms over a large but shallow edit. Copy source_id "
    "and project EXACTLY from the chosen candidate. Explain only what its subjects and paths support; do "
    "not invent code details. concept = 3-4 sentences; topic = a 2-4 word label; then quiz + answer. Return "
    "technical_thing = null when the block says there are no fresh candidates.\n"
    "- coach: ONE grounded nudge. GROUNDING (hard rule): only state a fact about Daniel that is dated "
    "and present in these inputs; never claim what the system 'is doing now' unless it is in the inputs; "
    "if you have no verifiable current fact, coach from a stable value. No platitudes.\n"
    "Plain hyphens only, never an em dash. No emoji."
)


def format_technical_candidates(candidates):
    if not candidates:
        return "(no fresh candidates - return technical_thing = null)"
    blocks = []
    for candidate in candidates:
        when = datetime.fromtimestamp(candidate.latest_time, PF.LUX).isoformat(timespec="minutes")
        blocks.append(
            f"SOURCE_ID: {candidate.cluster_id}\n"
            f"PROJECT: {candidate.project}\n"
            f"ACTIVITY_TIME: {when}\n"
            f"CHANGE_SUBJECTS: {' | '.join(candidate.subjects)}\n"
            f"CHANGED_PATHS: {', '.join(candidate.paths[:30])}"
        )
    return "\n\n".join(blocks)


def build_user(facts):
    return "\n".join([
        f"TODAY: {facts['date_line']}",
        f"\n=== AI TOPICS ALREADY COVERED (never repeat any) ===\n{facts['covered'][-1500:]}",
        f"\n=== RECENT AI NEWS (the ONLY source for AI ADVANCEMENTS - cite from these; if empty, keep it short) ===\n{facts['ai_news'] or '(no items fetched today)'}",
        f"\n=== TECHNICAL CANDIDATES (used source events removed; choose at most one) ===\n"
        f"{format_technical_candidates(facts['technical_candidates'])}",
        f"\n=== INBOX ({facts['reviewed_count']} emails, state-annotated) ===\n{facts['inbox_text']}",
        f"\n=== ALSO (already rendered by code, for your awareness) ===\nWeather: {facts['weather']}\n"
        f"Calendar:\n" + "\n".join(facts["calendar_lines"]),
    ])


@traceable(name="brief.compose", tags=["agent:brief", "env:prod"])
def compose(facts):
    return structured_call(MODEL, SYS, build_user(facts), Brief, max_tokens=3000)


# ---------- bind the model's judgment to the deterministic shortlist ----------

def validate_technical_source(brief, candidates):
    technical = brief.technical_thing
    if technical is None:
        return None
    return next(
        (
            candidate for candidate in candidates
            if candidate.cluster_id == technical.source_id
            and candidate.project == technical.project
        ),
        None,
    )


def technical_text(technical):
    return f"{technical.topic}\n{technical.concept}"


def compose_with_technical_gate(facts):
    """Compose once, then fail closed if its technical choice is hidden or repeated."""
    brief = compose(facts)
    technical = brief.technical_thing
    if technical is None:
        return brief, None, None, "", None
    semantic = technical_text(technical)
    selected = validate_technical_source(brief, facts["technical_candidates"])
    if selected is None:
        rejected = next(
            (
                candidate for candidate in facts["technical_candidates"]
                if candidate.cluster_id == technical.source_id
            ),
            None,
        )
        brief.technical_thing = None
        return brief, rejected, "rejected_invalid", semantic, None
    checked = filter_novel_with_vectors([semantic], store=PA.NOVELTY_STORE, fail_open=False)
    if not checked:
        brief.technical_thing = None
        return brief, selected, "rejected_repeat", semantic, None
    return brief, selected, "delivered", semantic, checked[0][1]


# ---------- deterministic render (format is code, not a creative choice) ----------

def render(brief, facts):
    L = [DIV, "NEEDS YOU TODAY", DIV]
    if brief.needs_you_today:
        L += [f"- {it.who}: {it.what} - {it.why_now}" for it in brief.needs_you_today]
    else:
        L.append("- Nothing needs a decision from you today.")
    L += ["", DIV, "TODAY", DIV, facts["weather"], *facts["calendar_lines"]]
    L += ["", DIV, "AI ADVANCEMENTS", DIV] + [f"- {a}" for a in brief.ai_advancements]
    t = brief.technical_thing
    if t is not None:
        L += ["", DIV, "ONE TECHNICAL THING", DIV, f"From project: {t.project}", t.concept]
        L += ["", f"Q: {t.quiz}", f"Answer: {t.answer}"]
    L += ["", DIV, "COACH", DIV, brief.coach]
    L += ["", facts["reviewed_line"]]
    return "\n".join(L)


def deliver(subject, email, brief, selected, technical_status, semantic, semantic_vector):
    """Send first, then record only state that was actually delivered."""
    subprocess.run(
        ["python3", SEND_EMAIL, subject],
        input=email,
        capture_output=True,
        text=True,
        check=True,
    )
    if selected is not None:
        if technical_status == "delivered":
            record_seen(
                [semantic],
                store=PA.NOVELTY_STORE,
                vectors=[semantic_vector],
                fail_silently=False,
            )
        PA.record_handled(selected, technical_status)
    record_seen(brief.ai_advancements)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="compose + print, do NOT send")
    a = ap.parse_args()

    facts = gather_facts()
    with tracing_context(metadata={"thread_id": "brief"}):   # group brief runs into one LangSmith thread
        brief, selected, technical_status, semantic, semantic_vector = compose_with_technical_gate(facts)
    subject = f"Morning brief - {facts['date_subject']}"
    email = render(brief, facts)

    if a.dry_run:
        print(f"Subject: {subject}\n\n{email}")
        return

    deliver(subject, email, brief, selected, technical_status, semantic, semantic_vector)
    try:  # every real morning is a benchmark fixture forever
        os.makedirs(FIXTURE_DIR, exist_ok=True)
        fixture = os.path.join(FIXTURE_DIR, datetime.now(PF.LUX).strftime("%Y-%m-%d") + ".txt")
        with open(fixture, "w", encoding="utf-8") as handle:
            handle.write(build_user(facts))
    except Exception:
        pass
    # the cron delivers this stdout to Telegram (no-agent script mode)
    print(f"Morning brief sent - {subject}. "
          f"{len(brief.needs_you_today)} need-you items, {facts['reviewed_count']} messages reviewed.\n"
          "Verdicts? (brief/coach/teacher: good|bad + notes)")


if __name__ == "__main__":
    main()
