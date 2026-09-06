#!/usr/bin/env python3
"""Brief v3 pre-fetch: the DETERMINISTIC tier (spec 2026-07-14).
Runs before the agent (hermes cron --script). Everything factual is gathered
by code and injected into the prompt; the model keeps only judgment + prose.

Emits a structured text block:
  weather, calendar (tz-verified), covered-topics tail, coverage cursor,
  inbox since cursor - noise-filtered (tier 1), state-annotated (tier 2):
  unread / already-replied / known-contact.
"""
import email, html as _html, imaplib, json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

LUX = ZoneInfo("Europe/Luxembourg")  # Daniel's TZ - the box is in Ireland; pin the date to Luxembourg

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))   # repo root, for shared.novelty
with open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8") as env_file:
    for line in env_file:
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)

# No code-side noise skip-list (removed 2026-08-11). The substring filter could silently
# drop a real email whose From header merely contained a noise word (a recruiter's reply
# nuked with no trace - the Bhairav/Tiff misses). We now pull EVERY inbox item since the
# cursor WITH a body snippet + Gmail's own STARRED/IMPORTANT labels, and let the one LLM
# call judge with full context. Tokens are trivial (~1k/brief); a false positive is far
# cheaper than a silently-dropped technical screen.


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


def snippet(msg, maxlen=300):
    """A clean plaintext preview of the body, so the model triages on content not just subject.
    Prefers text/plain; falls back to text/html with tags stripped + entities decoded (so
    HTML-only emails - like the CharacterQuilt screen - still get a readable snippet)."""
    def decode(part):
        try:
            return (part.get_payload(decode=True) or b"").decode(
                part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            return ""
    plain = htmlbody = ""
    for p in (msg.walk() if msg.is_multipart() else [msg]):
        ct = p.get_content_type()
        if ct == "text/plain" and not plain:
            plain = decode(p)
        elif ct == "text/html" and not htmlbody:
            htmlbody = decode(p)
    text = plain.strip() or htmlbody
    if "<" in text and ">" in text:                          # strip HTML if that's all we have
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[​-‍⁠﻿­]+", "", text)   # drop invisible preheader padding
    return re.sub(r"\s+", " ", text).strip()[:maxlen]


def inbox():
    cutoff = datetime.now().astimezone() - timedelta(hours=24)
    try:
        cutoff = datetime.fromisoformat(
            open(os.path.expanduser("~/.hermes/state/last_brief_sent")).read().strip())
    except Exception:
        pass
    known = known_contacts()
    rows = []
    with imaplib.IMAP4_SSL("imap.gmail.com") as im, imaplib.IMAP4_SSL("imap.gmail.com") as im2:
        im.login(os.environ["TWIN_SMTP_ADDRESS"], os.environ["TWIN_SMTP_APP_PASSWORD"])
        im2.login(os.environ["TWIN_SMTP_ADDRESS"], os.environ["TWIN_SMTP_APP_PASSWORD"])
        im.select("INBOX", readonly=True)
        im2.select('"[Gmail]/Sent Mail"', readonly=True)
        since = min(cutoff, datetime.now().astimezone() - timedelta(hours=24)).strftime("%d-%b-%Y")
        ok, d = im.search(None, f'(SINCE "{since}")')
        unparsed = 0
        for i in d[0].split():
            # X-GM-LABELS carries Gmail's own \\Starred / \\Important (Gmail's triage, which we
            # used to throw away); BODY.PEEK[] gets the body for the snippet without marking seen.
            ok, resp = im.fetch(i, "(FLAGS X-GM-LABELS BODY.PEEK[])")
            try:
                meta = " ".join(x[0].decode(errors="replace") if isinstance(x[0], bytes) else str(x[0])
                                for x in resp if isinstance(x, tuple))
                raw = next((x[1] for x in resp if isinstance(x, tuple) and isinstance(x[1], bytes)), b"")
                msg = email.message_from_bytes(raw)
                dt = parsedate_to_datetime(msg.get("Date"))
                if dt.timestamp() < cutoff.timestamp():
                    continue
            except Exception:
                unparsed += 1
                continue
            frm = str(make_header(decode_header(msg.get("From", "")))).lower()
            addr = (re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", frm) or [""])[0]
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            rows.append({
                "from": frm[:60], "subject": subject[:90], "date": dt.isoformat()[:16],
                "unread": "\\Seen" not in meta,
                "starred": "\\Starred" in meta,
                "important": "\\Important" in meta,
                "replied": replied_already(im2, subject, dt),
                "known_contact": addr in known,
                "body": snippet(msg),
            })
    lines = []
    for r in rows:
        flags = "UNREAD" if r["unread"] else "read"
        flags += "|STARRED" if r["starred"] else ""
        flags += "|IMPORTANT" if r["important"] else ""      # Gmail's own importance flag
        flags += "|REPLIED-ALREADY" if r["replied"] else ""
        flags += "|KNOWN" if r["known_contact"] else ""
        line = f"- [{flags}] {r['date']} | {r['from']} | {r['subject']}"
        if r["body"]:
            line += f"\n    {r['body']}"
        lines.append(line)
    return (f"(ALL inbox since cursor {cutoff.isoformat()[:16]}; {unparsed} unparseable - if >0 investigate, "
            f"never hide)\n" + ("\n".join(lines) or "(no emails)")), len(rows)


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
        try:   # novelty gate: drop items close to what the brief already surfaced (fail-open)
            from shared.novelty import filter_novel
            cands = [f"{h.get('title','')} {' '.join((h.get('content') or '').split())[:200]}" for h in hits]
            keep = set(filter_novel(cands))
            hits = [h for h, c in zip(hits, cands) if c in keep]
        except Exception:
            pass
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
