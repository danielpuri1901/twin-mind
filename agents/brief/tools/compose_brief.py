#!/usr/bin/env python3
"""Morning brief - the PROD-READY pipeline (reference implementation for the whole system).

Deterministic-by-default. The brief used to be an autonomous agent that composed + assembled +
sent, which is why it hit cron approval-gates and guessed the date. This replaces it with a
straight-line pipeline and exactly ONE constrained LLM call:

    gather_facts()   deterministic - weather, calendar, state-annotated inbox, counts, date,
                     covered-topics, the top CHANGELOG entry (reuses prefetch.py's functions)
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
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # tools->brief->agents->super-project
sys.path.insert(0, HERE)                                # prefetch
sys.path.insert(0, REPO)                                # shared.structured
import prefetch as PF
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
    topic: str         # 2-4 word label for dedup, e.g. "prompt caching" - never taught twice
    concept: str       # 3-4 sentences teaching the concept
    code_path: str     # the real file path referenced by the CHANGELOG entry
    code_symbol: str   # the EXACT def/class/function name in code_path to show; the code itself is injected by us, never written by the model
    quiz: str          # one question
    answer: str        # its answer


class Brief(BaseModel):
    """Daniel's morning brief - SECTION CONTENT ONLY. The format, subject, date, message-count line,
    and the TODAY block (weather + calendar) are rendered deterministically by code, never here."""
    needs_you_today: list[NeedsItem]   # section 1; empty list if nothing needs a decision
    ai_advancements: list[str]         # section 3; 2-3 insight items, none on the covered list
    technical_thing: TechnicalThing    # section 4
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
    try:
        technical_taught = open(os.path.expanduser("~/.hermes/state/technical-covered.txt")).read().strip()
    except Exception:
        technical_taught = "(none yet)"
    return {
        "date_subject": f"{now.strftime('%A')} {now.day} {now.strftime('%B')}",
        "date_line": f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y')} (Europe/Luxembourg)",
        "weather": PF.weather(),
        "calendar_lines": cal.splitlines() if cal else ["(no events)"],
        "inbox_text": inbox_text,
        "reviewed_count": n,
        "reviewed_line": f"Reviewed {n} messages since {cursor}",
        "covered": covered,
        "technical_item": PF.technical_item(),
        "changelog": PF.changelog_top(),
        "technical_taught": technical_taught,
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
    "- technical_thing: teach the concept under the TOP CHANGELOG ENTRY (what was just built or broke). "
    "concept = 3-4 sentences; code_path = the real file that entry references; code_symbol = the EXACT "
    "name of a function or class defined in that file to showcase (e.g. 'structured_call') - DO NOT write "
    "any code, the system inserts the real lines for that symbol automatically. If the concept has NO "
    "real file in THIS repo (a purely external or conceptual item), set code_path and code_symbol to "
    "EMPTY strings so the code block is omitted - NEVER invent a path. quiz + answer; topic = a "
    "2-4 word label. HARD RULE: topic must NOT be on the already-taught list - if the top entry's concept "
    "was already taught, teach a DIFFERENT concept from the entry, or use the quiet-day fallback item.\n"
    "- coach: ONE grounded nudge. GROUNDING (hard rule): only state a fact about Daniel that is dated "
    "and present in these inputs; never claim what the system 'is doing now' unless it is in the inputs; "
    "if you have no verifiable current fact, coach from a stable value. No platitudes.\n"
    "Plain hyphens only, never an em dash. No emoji."
)


def build_user(facts):
    return "\n".join([
        f"TODAY: {facts['date_line']}",
        f"\n=== AI TOPICS ALREADY COVERED (never repeat any) ===\n{facts['covered'][-1500:]}",
        f"\n=== RECENT AI NEWS (the ONLY source for AI ADVANCEMENTS - cite from these; if empty, keep it short) ===\n{facts['ai_news'] or '(no items fetched today)'}",
        f"\n=== TOP CHANGELOG ENTRY (source for the technical section) ===\n{facts['changelog']}",
        f"\n=== TECHNICAL TOPICS ALREADY TAUGHT (do NOT teach any of these again) ===\n{facts['technical_taught'][-800:]}",
        f"\n=== QUIET-DAY FALLBACK TECHNICAL ITEM (only if the CHANGELOG entry is not teachable) ===\n{facts['technical_item']}",
        f"\n=== INBOX ({facts['reviewed_count']} emails, state-annotated) ===\n{facts['inbox_text']}",
        f"\n=== ALSO (already rendered by code, for your awareness) ===\nWeather: {facts['weather']}\n"
        f"Calendar:\n" + "\n".join(facts["calendar_lines"]),
    ])


@traceable(name="brief.compose", tags=["agent:brief", "env:prod"])
def compose(facts):
    return structured_call(MODEL, SYS, build_user(facts), Brief, max_tokens=3000)


# ---------- inject the real code (the model names a symbol; code supplies the bytes) ----------

def _list_symbols(text):
    """Top-level def/class/assignment names in a source file - the valid choices for code_symbol."""
    out = []
    for ln in text.splitlines():
        m = re.match(r"^\s*(?:async\s+def|def|class)\s+(\w+)", ln) or re.match(r"^(\w+)\s*=(?!=)", ln)
        if m:
            out.append(m.group(1))
    return out


def extract_symbol(repo_root, code_path, symbol):
    """Return (verbatim block for `symbol`, available symbols). The model never writes code; this
    pulls the real lines from the file so the quote cannot be fabricated. quote is None if absent."""
    path = re.sub(r":\d+(-\d+)?\s*$", "", (code_path or "").strip())
    full = path if os.path.isabs(path) else os.path.join(repo_root, path)
    if not os.path.isfile(full):
        return None, []
    lines = open(full, encoding="utf-8", errors="replace").read().splitlines()
    avail = _list_symbols("\n".join(lines))
    pat = re.compile(rf"^(\s*)(?:async\s+def|def|class)\s+{re.escape(symbol)}\b"
                     rf"|^(\s*){re.escape(symbol)}\s*=(?!=)")
    start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
    if start is None:
        return None, avail
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    for j in range(start + 1, min(len(lines), start + 16)):
        if lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip())) <= indent:
            break
        end = j + 1
    return "\n".join(lines[start:end]).rstrip(), avail


def compose_with_real_code(facts):
    """Compose, then inject the REAL code for the symbol the model named. Fail CLOSED, never faked:
    the model may set code_path empty when the concept has no repo code; if it names a path/symbol
    that does not resolve, retry once with the real options; if it still does not resolve, return no
    quote and render concept+quiz WITHOUT a code block. A '[not found]' string is never shipped."""
    brief = compose(facts)
    t = brief.technical_thing
    if not (t.code_path or "").strip():          # model opted out - concept has no repo code
        return brief, None
    quote, avail = extract_symbol(REPO, t.code_path, t.code_symbol)
    if quote is None:                            # wrong symbol OR non-existent file - one correction
        why = (f"code_symbol must be exactly one of: {', '.join(avail[:20])}." if avail
               else f"'{t.code_path}' is not a file in this repo.")
        hint = (f"\n\nCORRECTION: could not find '{t.code_symbol}' in '{t.code_path}'. {why} "
                "Name a file that really exists and defines the symbol, OR if this concept has no "
                "code in this repo, set code_path and code_symbol to empty strings.")
        brief = structured_call(MODEL, SYS, build_user(facts) + hint, Brief, max_tokens=3000)
        t = brief.technical_thing
        quote = (None if not (t.code_path or "").strip()
                 else extract_symbol(REPO, t.code_path, t.code_symbol)[0])
    return brief, quote                          # None => render omits the code block (fail closed)


# ---------- deterministic render (format is code, not a creative choice) ----------

def render(brief, facts, code_quote):
    L = [DIV, "NEEDS YOU TODAY", DIV]
    if brief.needs_you_today:
        L += [f"- {it.who}: {it.what} - {it.why_now}" for it in brief.needs_you_today]
    else:
        L.append("- Nothing needs a decision from you today.")
    L += ["", DIV, "TODAY", DIV, facts["weather"], *facts["calendar_lines"]]
    L += ["", DIV, "AI ADVANCEMENTS", DIV] + [f"- {a}" for a in brief.ai_advancements]
    t = brief.technical_thing
    L += ["", DIV, "ONE TECHNICAL THING", DIV, t.concept]
    if code_quote and code_quote.strip():
        L += ["", f"{t.code_path}:", code_quote]
    L += ["", f"Q: {t.quiz}", f"Answer: {t.answer}"]
    L += ["", DIV, "COACH", DIV, brief.coach]
    L += ["", facts["reviewed_line"]]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="compose + print, do NOT send")
    a = ap.parse_args()

    facts = gather_facts()
    with tracing_context(metadata={"thread_id": "brief"}):   # group brief runs into one LangSmith thread
        brief, code_quote = compose_with_real_code(facts)   # ONE LLM call + deterministic code injection
    subject = f"Morning brief - {facts['date_subject']}"
    email = render(brief, facts, code_quote)         # deterministic

    if a.dry_run:
        print(f"Subject: {subject}\n\n{email}")
        return

    r = subprocess.run(["python3", SEND_EMAIL, subject], input=email, capture_output=True, text=True)
    try:  # record the technical topic so it is never taught twice (deterministic dedup)
        with open(os.path.expanduser("~/.hermes/state/technical-covered.txt"), "a") as f:
            f.write(f"{facts['date_subject']}: {brief.technical_thing.topic}\n")
    except Exception:
        pass
    try:  # record the AI-advancement insights actually surfaced -> semantic novelty gate next run
        from shared.novelty import record as record_seen
        record_seen(brief.ai_advancements)
    except Exception:
        pass
    try:  # every real morning is a benchmark fixture forever
        os.makedirs(FIXTURE_DIR, exist_ok=True)
        open(os.path.join(FIXTURE_DIR, datetime.now(PF.LUX).strftime("%Y-%m-%d") + ".txt"), "w").write(build_user(facts))
    except Exception:
        pass
    # the cron delivers this stdout to Telegram (no-agent script mode)
    print(f"Morning brief sent - {subject}. "
          f"{len(brief.needs_you_today)} need-you items, {facts['reviewed_count']} messages reviewed.\n"
          "Verdicts? (brief/coach/teacher: good|bad + notes)")


if __name__ == "__main__":
    main()
