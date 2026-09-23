#!/usr/bin/env python3
"""ingest_wispr_meetings.py - box-side Wispr Flow meeting ingester (2026-09-23).

Replaces the Granola summary ingester (ingest_meeting_summaries.py): Daniel moved meeting capture
from Granola to Wispr Flow Notetaker. Wispr Flow's official remote MCP (read-only) returns the
VERBATIM transcript plus a summary, so the twin gets more than Granola ever gave it.

Design (same shape as the Granola ingester, which ran clean for two months):
  - Runs ON THE BOX (systemd timer, every 4h). The box is the SINGLE owner of this OAuth token
    family (~/.hermes/mcp-tokens/wispr-ingest.json). Refresh tokens rotate; a second consumer
    (a gateway MCP entry, a Mac copy) kills the family within hours - the July Granola deaths.
  - Speaks MCP JSON-RPC over streamable HTTP directly, refreshes its own token (atomic write-back).
  - Two layers per meeting (chunking design 2026-07-17): one summary record for broad queries,
    plus windowed transcript chunks (~1600 chars, ~25% overlap) for specifics. Every record text
    carries the contextual "[<chat> · <date>]" prefix, same as the promoted corpus.
  - INCREMENTAL index inserts only (corpus.db FTS + vectors.db). NEVER a rebuild - that would
    revert the windowed+contextual promotion on the box.
  - Only FINALIZED meetings ingest; an unfinished one is skipped and re-checked next run.
  - Backfill (Daniel's ruling): every meeting Wispr Flow already holds ingests on the first run.
  - Heartbeat: CloudWatch TwinMind/MeetingIngestRan (job ran) + MeetingsIngested (meetings saved);
    alarms fire on 12h without a run and on 7 days without a new meeting.
  - Transcripts are DATA: speaker labels and text are stored, never executed or obeyed.

Silent when healthy; prints actions and problems.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chunk_conversations import window  # noqa: E402  the production windowing, reused as-is

HOME = os.path.expanduser("~")
TOKEN_FILE = os.path.join(HOME, ".hermes", "mcp-tokens", "wispr-ingest.json")
CLIENT_FILE = os.path.join(HOME, ".hermes", "mcp-tokens", "wispr-ingest.client.json")
STATE = os.path.join(HOME, ".hermes", "state", "wispr-ingest-state.json")
CORPUS = os.environ.get("TWIN_CORPUS", os.path.join(HOME, "twin-corpus"))
FTS_DB = os.path.join(CORPUS, "index", "corpus.db")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")
INBOX = os.path.join(CORPUS, "transcripts-inbox")

MCP_URL = "https://api.wisprflow.ai/connect/mcp"
EMBED_MODEL = "cohere.embed-multilingual-v3"
SOURCE = "meeting"
PAGE_CHARS = 40000  # server-enforced max per get_meeting transcript range


# ---------------------------------------------------------------- token
def token_endpoint():
    """Read the token URL from the saved OAuth metadata when present, else discover it."""
    meta = TOKEN_FILE.replace(".json", ".meta.json")
    try:
        return json.load(open(meta))["token_endpoint"]
    except Exception:
        pass
    with urllib.request.urlopen("https://mcp-auth.wisprflow.com/.well-known/oauth-authorization-server",
                                timeout=30) as r:
        return json.loads(r.read())["token_endpoint"]


def load_token():
    tok = json.load(open(TOKEN_FILE))
    if tok.get("expires_at", 0) > time.time() + 60:
        return tok["access_token"]
    client_id = json.load(open(CLIENT_FILE))["client_id"]
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
        "client_id": client_id,
        "resource": MCP_URL,
    }).encode()
    req = urllib.request.Request(token_endpoint(), data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        new = json.loads(r.read())
    new["expires_at"] = time.time() + float(new.get("expires_in", 3600))
    if "refresh_token" not in new:
        new["refresh_token"] = tok["refresh_token"]
    tmp = TOKEN_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(new, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TOKEN_FILE)
    return new["access_token"]


# ---------------------------------------------------------------- MCP client
def _post(token, payload, session=None):
    req = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    if session:
        req.add_header("Mcp-Session-Id", session)
    with urllib.request.urlopen(req, timeout=60) as r:
        sid = r.headers.get("Mcp-Session-Id") or session
        raw = r.read().decode()
    if raw.lstrip().startswith("event:") or "\ndata:" in raw or raw.startswith("data:"):
        data_lines = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")]
        raw = data_lines[-1] if data_lines else "{}"
    return (json.loads(raw) if raw.strip() else {}), sid


def mcp_connect(token):
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "twin-wispr-ingest", "version": "1.0"}}}
    resp, sid = _post(token, init)
    if "error" in resp:
        raise RuntimeError(f"MCP initialize failed: {resp['error']}")
    try:  # notification; some servers answer 202 with an empty body
        _post(token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    except urllib.error.HTTPError:
        pass
    return sid


def mcp_call(token, sid, tool, args):
    """Call a tool and return its JSON result (Wispr Flow tools answer with one JSON text block)."""
    payload = {"jsonrpc": "2.0", "id": int(time.time() * 1000) % 10**9,
               "method": "tools/call", "params": {"name": tool, "arguments": args}}
    resp, _ = _post(token, payload, sid)
    if "error" in resp:
        raise RuntimeError(f"{tool} error: {resp['error']}")
    result = resp.get("result", {})
    if result.get("isError"):
        raise RuntimeError(f"{tool} tool error: {str(result.get('content'))[:200]}")
    if result.get("structuredContent"):
        return result["structuredContent"]
    text = "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    return json.loads(text)


# ---------------------------------------------------------------- fetch
def list_meetings(call):
    """Every meeting, newest first, following the cursor until has_more is false."""
    out, cursor = [], None
    while True:
        args = {"limit": 200}
        if cursor:
            args["cursor"] = cursor
        page = call("search_meetings", args)
        out.extend(page.get("meetings", []))
        if not page.get("has_more"):
            return out
        cursor = page["next_cursor"]


TRUNC = re.compile(r"\n*\(\.\.\.truncated, \d+ chars remaining; continue with view_transcript\.start_char=(\d+)\.\.\.\)")
FENCE = re.compile(r"<<<[^>]*>>>")


def fetch_transcript(call, meeting_id):
    """Full transcript text, reading every bounded range. Returns (summary, title, transcript)."""
    parts, start, summary, title = [], 0, "", ""
    while True:
        m = call("get_meeting", {"meeting_id": meeting_id,
                                 "view_transcript": {"start_char": start, "char_limit": PAGE_CHARS},
                                 "view_content": {"char_limit": 1}})
        summary, title = m.get("summary") or summary, m.get("title") or title
        chunk = m.get("transcript") or ""
        nxt = TRUNC.search(chunk)
        parts.append(FENCE.sub("", TRUNC.sub("", chunk)))
        if not nxt or int(nxt.group(1)) <= start:
            break
        start = int(nxt.group(1))
    return summary, title, "".join(parts)


# ---------------------------------------------------------------- records
def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60] or "untitled"


def meeting_title(title, summary):
    """Wispr Flow leaves many titles empty. Fall back to the summary's first sentence."""
    if (title or "").strip():
        return title.strip()
    first = re.split(r"(?<=[.!?])\s", (summary or "").strip(), maxsplit=1)[0]
    return first[:80].strip() or "Untitled meeting"


def turns(transcript):
    """'Speaker 1: text' lines -> per-turn dicts in the shape chunk_conversations.window() reads."""
    out = []
    for line in transcript.splitlines():
        m = re.match(r"\s*([^:\n]{1,60}):\s+(.*\S)", line)
        if m:
            out.append({"sender": m.group(1).strip(), "text": m.group(2).strip()})
        elif line.strip() and out:
            out[-1]["text"] += " " + line.strip()
    return out


SUMMARY_MAX = 1800  # leaves room for the context prefix under the 2048-char embed cap


def summary_parts(text):
    """Wispr summaries run to ~3000 chars. Pack whole '### ' sections into parts <= SUMMARY_MAX,
    so nothing is cut off at embed time. A single oversized section is hard-split as a last resort."""
    if not text:
        return []
    sections = re.split(r"\n(?=### )", text)
    parts, cur = [], ""
    for sec in sections:
        while len(sec) > SUMMARY_MAX:
            if cur:
                parts.append(cur); cur = ""
            parts.append(sec[:SUMMARY_MAX]); sec = sec[SUMMARY_MAX:]
        if cur and len(cur) + 1 + len(sec) > SUMMARY_MAX:
            parts.append(cur); cur = sec
        else:
            cur = f"{cur}\n{sec}" if cur else sec
    if cur:
        parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def make_records(meeting, title, summary, transcript):
    """Two layers: one summary record + windowed transcript chunks, all context-prefixed."""
    date = (meeting.get("start") or meeting.get("modified_at") or "")[:19]
    day = date[:10]
    chat = f"{day}-{slugify(title)}"
    head = f"[{chat} · {day}]\n"
    recs = [{"source": SOURCE, "chat": chat, "date": date, "who": "summary", "sender": "", "text": head + part}
            for part in summary_parts(f"{title}\n{summary.strip()}" if summary.strip() else "")]
    t = turns(transcript)
    if t:
        for r in t:
            r.update(source=SOURCE, chat=chat, date=date)
        for w in window(t):
            recs.append({**w, "date": date, "text": head + w["text"]})
    return chat, recs


# ---------------------------------------------------------------- index (INCREMENTAL ONLY)
def index_records(recs):
    import sqlite3
    import boto3
    import sqlite_vec
    db = sqlite3.connect(FTS_DB)
    db.executemany("INSERT INTO msgs VALUES (?,?,?,?,?,?)",
                   [(r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"]) for r in recs])
    db.commit(); db.close()
    brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
    vecs = []
    for i in range(0, len(recs), 90):  # Cohere v3 takes up to 96 texts per call
        body = json.dumps({"texts": [r["text"][:2048] for r in recs[i:i + 90]],
                           "input_type": "search_document", "truncate": "END"})
        vecs += json.loads(brt.invoke_model(modelId=EMBED_MODEL, body=body)["body"].read())["embeddings"]
    db = sqlite3.connect(VEC_DB)
    db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
    rid = db.execute("SELECT COALESCE(MAX(rowid),0) FROM vec_meta").fetchone()[0]
    for r, v in zip(recs, vecs):
        rid += 1
        db.execute("INSERT INTO vec_meta VALUES (?,?,?,?,?,?,?)",
                   (rid, r["source"], r["chat"], r["date"], r["who"], r["sender"], r["text"]))
        db.execute("INSERT INTO vec_idx(rowid, embedding) VALUES (?,?)", (rid, sqlite_vec.serialize_float32(v)))
    db.commit(); db.close()


def heartbeat(saved=0):
    """MeetingIngestRan = the job ran (dead-man). MeetingsIngested = how many meetings it saved,
    so a feed that runs but brings nothing new (the Granola failure, 2 silent months) alarms too."""
    try:
        import boto3
        boto3.client("cloudwatch", region_name="eu-west-1").put_metric_data(
            Namespace="TwinMind", MetricData=[{"MetricName": "MeetingIngestRan", "Value": 1},
                                              {"MetricName": "MeetingsIngested", "Value": saved}])
    except Exception as e:
        print(f"heartbeat failed (non-fatal): {e}", file=sys.stderr)


# ---------------------------------------------------------------- main
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="connect + list only; ingest nothing")
    a = ap.parse_args()

    token = load_token()
    sid = mcp_connect(token)
    call = lambda tool, args: mcp_call(token, sid, tool, args)  # noqa: E731
    meetings = list_meetings(call)
    if a.probe:
        print(f"wispr MCP ok: {len(meetings)} meetings")
        for m in meetings[:5]:
            print(f"  {(m.get('start') or '')[:10]}  {(m.get('title') or '(untitled)')[:60]}"
                  f"  finalized={m.get('finalized')} transcript={m.get('has_transcript')}")
        return

    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    new = [m for m in meetings if m["id"] not in state and m.get("finalized")]
    saved = failed = 0
    os.makedirs(INBOX, exist_ok=True)
    for m in reversed(new):  # oldest first, so a partial run leaves a clean prefix
        try:
            summary, title, transcript = fetch_transcript(call, m["id"])
            title = meeting_title(title, summary)
            chat, recs = make_records(m, title, summary, transcript)
            if not recs:
                print(f"meeting empty [{title[:50]}] - retry next run")
                continue
            index_records(recs)
            with open(os.path.join(INBOX, f"{chat}.md"), "w", encoding="utf-8") as f:
                f.write(f"Meeting: {title}\nDate: {m.get('start')}\nSource: Wispr Flow, auto-ingested "
                        f"{datetime.now().strftime('%Y-%m-%d')}\n\n## Summary\n\n{summary.strip()}\n\n"
                        f"## Transcript\n\n{transcript.strip()}\n")
            state[m["id"]] = {"status": "saved", "title": title, "date": m.get("start"),
                              "file": f"{chat}.md", "records": len(recs)}
            saved += 1
            print(f"ingested meeting: {title[:60]} ({(m.get('start') or '')[:10]}, {len(recs)} records)")
        except Exception as e:
            failed += 1
            print(f"MEETING INGEST FAILED [{(m.get('title') or m['id'])[:50]}]: {str(e)[:150]}")
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(state, open(STATE, "w"), indent=1)
    if saved or failed:
        print(f"wispr ingest: saved={saved} failed={failed}")
    heartbeat(saved)


if __name__ == "__main__":
    main()
