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
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

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


def main():
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
