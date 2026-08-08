#!/usr/bin/env python3
"""Brief v3 pre-fetch: the DETERMINISTIC tier (spec 2026-07-14).
Runs before the agent (hermes cron --script). Everything factual is gathered
by code and injected into the prompt; the model keeps only judgment + prose.

Emits a structured text block:
  weather, calendar (tz-verified), covered-topics tail, coverage cursor,
  inbox since cursor - noise-filtered (tier 1), state-annotated (tier 2):
  unread / already-replied / known-contact.
"""
import email, imaplib, json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

LUX = ZoneInfo("Europe/Luxembourg")  # Daniel's TZ - the box is in Ireland; pin the date to Luxembourg

HERE = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.expanduser("~/.hermes/.env")):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

# Tier 1: known noise - the model never sees these (OPERATIONS.md skip-list)
NOISE = ("linkedin.com", "medium.com", "nytimes.com", "theguardian.com", "masterclass.com",
         "expressvpn", "dailystoic", "thuisbezorgd", "newyorkpizza", "sovendus", "duo.nl",
         "urbanoutfitters", "kodekloud", "wispr", "startupschool@ycombinator.com",
         "no-reply@flixbus", "nsinternational", "skratch", "pearle", "apple.com/news",
         "glassdoor", "jobalert.indeed", "beehiiv", "rockhal", "youngla",
         "marketing-ops@gurobi", "emcom.bankofamerica")
# always-surface exceptions override the noise tier
ALWAYS = ("costalerts.amazonaws.com", os.environ.get("TWIN_SMTP_ADDRESS", "").lower())


def out(title, body):
    print(f"\n=== {title} ===\n{body.strip()}")


def weather():
    # Jul-15 2026: a single-shot request got a transient Open-Meteo 503 and the brief
    # showed no weather. Now: retry with backoff, then fall back to a second source.
    om = ("https://api.open-meteo.com/v1/forecast?latitude=49.61&longitude=6.13"
          "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
          "&timezone=Europe%2FLuxembourg&forecast_days=1")
    last = ""
    for attempt in range(4):
        try:
            d = json.load(urllib.request.urlopen(om, timeout=15))["daily"]
            return (f"Luxembourg: {d['temperature_2m_min'][0]:.0f}-{d['temperature_2m_max'][0]:.0f}°C, "
                    f"rain chance {d['precipitation_probability_max'][0]}%")
        except Exception as e:
            last = str(e)
            if attempt < 3:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
    try:  # fallback so weather still shows if Open-Meteo is fully down
        w = json.load(urllib.request.urlopen("https://wttr.in/Luxembourg?format=j1", timeout=15))["weather"][0]
        return (f"Luxembourg: {w['mintempC']}-{w['maxtempC']}°C, "
                f"rain chance {w['hourly'][4].get('chanceofrain', '?')}% (via wttr.in)")
    except Exception as e2:
        return f"(weather unavailable: open-meteo {last}; wttr {e2})"


def known_contacts():
    known = set()
    try:
        for l in open(os.path.expanduser("~/twin-corpus/normalized/contacts.jsonl")):
            r = json.loads(l)
            for e_ in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", json.dumps(r)):
                known.add(e_.lower())
    except Exception:
        pass
    return known


def replied_already(im_sent, subject, after_dt):
    """Did Daniel send anything on this subject after the mail arrived?"""
    try:
        subj = re.sub(r'^(Re|Fwd?):\s*', '', subject, flags=re.I)[:40].replace('"', "")
        since = after_dt.strftime("%d-%b-%Y")
        ok, d = im_sent.search(None, f'(SINCE "{since}" SUBJECT "{subj}")')
        return ok == "OK" and bool(d[0].split())
    except Exception:
        return False


def inbox():
    cutoff = datetime.now().astimezone() - timedelta(hours=24)
    try:
        cutoff = datetime.fromisoformat(
            open(os.path.expanduser("~/.hermes/state/last_brief_sent")).read().strip())
    except Exception:
        pass
    known = known_contacts()
    rows, skipped = [], 0
    with imaplib.IMAP4_SSL("imap.gmail.com") as im, imaplib.IMAP4_SSL("imap.gmail.com") as im2:
        im.login(os.environ["TWIN_SMTP_ADDRESS"], os.environ["TWIN_SMTP_APP_PASSWORD"])
        im2.login(os.environ["TWIN_SMTP_ADDRESS"], os.environ["TWIN_SMTP_APP_PASSWORD"])
        im.select("INBOX", readonly=True)
        im2.select('"[Gmail]/Sent Mail"', readonly=True)
        since = min(cutoff, datetime.now().astimezone() - timedelta(hours=24)).strftime("%d-%b-%Y")
        ok, d = im.search(None, f'(SINCE "{since}")')
        unparsed = 0
        for i in d[0].split():
            ok, hdr = im.fetch(i, "(FLAGS BODY.PEEK[HEADER])")
            try:
                flags = next((x[0].decode() if isinstance(x[0], bytes) else str(x[0])
                              for x in hdr if isinstance(x, tuple)), "")
                raw = next((x[1] for x in hdr if isinstance(x, tuple) and isinstance(x[1], bytes)), b"")
                msg = email.message_from_bytes(raw)
                dt = parsedate_to_datetime(msg.get("Date"))
                if dt.timestamp() < cutoff.timestamp():
                    continue
            except Exception:
                unparsed += 1
                continue
            frm = str(make_header(decode_header(msg.get("From", "")))).lower()
            addr = (re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", frm) or [""])[0]
            if any(n in frm for n in NOISE) and not any(a and a in frm for a in ALWAYS):
                skipped += 1
                continue
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            unread = "\\Seen" not in flags
            rows.append({
                "from": frm[:60], "subject": subject[:90], "date": dt.isoformat()[:16],
                "unread": unread,
                "replied": replied_already(im2, subject, dt),
                "known_contact": addr in known,
            })
    lines = [f"- [{'UNREAD' if r['unread'] else 'read'}"
             f"{'|REPLIED-ALREADY' if r['replied'] else ''}"
             f"{'|KNOWN' if r['known_contact'] else ''}] "
             f"{r['date']} | {r['from']} | {r['subject']}" for r in rows]
    return (f"(since cursor {cutoff.isoformat()[:16]}; {skipped} noise filtered by code; "
            f"{unparsed} unparseable - if >0 investigate, never hide)\n"
            + ("\n".join(lines) or "(no emails)")), len(rows)


def technical_item():
    """Source-inject the quiet-day fallback item so the model never does the fragile
    'day-of-year mod item-count' arithmetic itself. That arithmetic is what made past teacher
    sections wrong (stale count: the list is numbered 1-13 but has a hidden '3b' = 14 items).
    Code counts the list and picks the item deterministically; the model just teaches it."""
    try:
        path = os.path.expanduser("~/twin-corpus/wiki/learning/digest-queue.md")
        items = []
        for line in open(path):
            m = re.match(r"\s*(\d+[a-z]?)\.\s+(.+)", line)
            if m:
                items.append((m.group(1), m.group(2).strip()))
        if not items:
            return "(digest-queue.md unparseable - teach from the CHANGELOG top entry instead)"
        doy = datetime.now().timetuple().tm_yday
        idx = doy % len(items)
        label, text = items[idx]
        return (f'day-of-year {doy} mod {len(items)} items = index {idx} -> item "{label}": {text}\n'
                f"(code-picked; do NOT recompute - use this exact item on a quiet day)")
    except Exception as e:
        return f"(technical_item failed, non-fatal - teach from the CHANGELOG top entry: {e})"


def changelog_top():
    """The top CHANGELOG entry - the source for the ONE TECHNICAL THING section. Injected so the
    composer teaches from what we just built/broke WITHOUT reading files itself (deterministic,
    no tool calls in the compose step)."""
    try:
        path = os.path.expanduser("~/super-project/docs/CHANGELOG.md")
        lines, capturing = [], False
        for line in open(path, encoding="utf-8"):
            if line.startswith("## 2"):          # a dated entry header
                if capturing:
                    break                          # reached the next entry -> stop
                capturing = True
            if capturing:
                lines.append(line.rstrip())
                if sum(len(x) for x in lines) > 2800:
                    break
        return "\n".join(lines).strip() or "(CHANGELOG empty)"
    except Exception as e:
        return f"(changelog unavailable: {e})"


def ai_news():
    """Recent AI news, fetched by CODE so AI ADVANCEMENTS is grounded in real sources instead of
    the model inventing lab measurements. Tavily news search (official SDK, ~1 credit/call);
    returns '' on any failure so the brief never breaks - a quiet news block just shortens that
    section. The composer is told to cite ONLY from these items."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return ""
    try:
        from tavily import TavilyClient
        hits = TavilyClient(api_key=key).search(
            "major AI model releases, research results, and developer tool launches announced this week by AI labs and companies",
            topic="news", time_range="week", max_results=10,
            exclude_domains=["instagram.com", "facebook.com", "tiktok.com", "medium.com",
                             "youtube.com", "reddit.com", "linkedin.com",
                             "prnewswire.com", "businesswire.com"])["results"]
        return "\n".join(
            f"- {h['title'].strip()} ({(h.get('published_date') or '')[:10]}) - "
            f"{' '.join((h.get('content') or '').split())[:220]} [{h.get('url', '')}]"
            for h in hits)
    except Exception:
        return ""


def today_block():
    """Authoritative date, injected so the model never runs `date` (denied under cron_mode:deny)
    and never guesses it (the 2026-07-24 'Friday 25 July' bug). Europe/Luxembourg = Daniel's TZ."""
    now = datetime.now(LUX)
    subj = f"{now.strftime('%A')} {now.day} {now.strftime('%B')}"   # "Friday 24 July" - portable, no leading zero
    return (f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y')} (Europe/Luxembourg)\n"
            f"Subject line MUST be EXACTLY: Morning brief - {subj}")


def main():
    out("TODAY (authoritative - use THIS date; never run `date`, never compute it)", today_block())
    w = weather()
    out("WEATHER (code-fetched, Open-Meteo)", w)
    cal = subprocess.run(["python3", os.path.join(HERE, "calendar_read.py"), "--days", "1"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    out("CALENDAR (times already local/verified)", cal or "(no events)")
    try:
        cov = open(os.path.expanduser("~/.hermes/state/digest-covered.txt")).read().strip()
    except Exception:
        cov = "(none yet)"
    out("AI TOPICS ALREADY COVERED (do NOT repeat any of these)", cov[-1500:])
    out("QUIET-DAY FALLBACK TECHNICAL ITEM (code-picked; use ONLY if no CHANGELOG-worthy incident)",
        technical_item())
    ib, n = inbox()
    out(f"INBOX ({n} emails after noise filter, state-annotated)", ib)
    out("YOUR JOB", "Judge substance on the emails above (the state flags are facts - trust them). "
        "Compose the brief per the FORMAT CONTRACT. The coverage line count is exactly "
        f"{n} messages since the cursor shown above.")


if __name__ == "__main__":
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    text = buf.getvalue()
    print(text)
    try:  # fixture archive: every real morning becomes a benchmark input forever
        fd = os.path.expanduser("~/twin-corpus/datasets/brief-inputs")
        os.makedirs(fd, exist_ok=True)
        open(os.path.join(fd, datetime.now().strftime("%Y-%m-%d") + ".txt"), "w").write(text)
    except Exception as e:
        print(f"(fixture archive failed, non-fatal: {e})")
