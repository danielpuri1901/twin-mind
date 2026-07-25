#!/usr/bin/env python3
"""ingest_meeting_summaries.py - box-side Granola SUMMARY ingester (2026-07-24).

Replaces the dead verbatim-transcript poller (fetch_granola.py, Mac): Granola 7.441 encrypted its
whole local store, and the official API gates verbatim transcripts behind a paid tier. Daniel's
ruling (option 1): ingest the OFFICIAL MCP's meeting summaries instead - free and robust, survives
Granola app updates because it never touches local storage.

Design:
  - Runs ON THE BOX (systemd timer, every 4h). The box is the SINGLE owner of the Granola MCP
    OAuth token (~/.hermes/mcp-tokens/granola.json) - never use granola from Mac-side Hermes;
    refresh tokens rotate and two consumers invalidate each other (the July token deaths).
  - Speaks MCP JSON-RPC over streamable HTTP directly (initialize -> tools/call), Bearer token
    from the shared token file; refreshes it itself if expired (atomic write-back to the same
    file the gateway reads, so there is one token state, not two).
  - INCREMENTAL index updates only: INSERT into the live corpus.db (FTS5) and vectors.db
    (vec_meta/vec_idx). NEVER a rebuild - the box's normalized/ still holds pre-promotion
    per-turn data, so build_index.py/embed_corpus.py main() would REVERT the 2026-07-21
    windowed+contextual promotion.
  - Contextual embedding: text is prefixed "[<title> . <date>]" to match the promoted design.
  - Scope: baseline-marks meetings already known at first run (their verbatim transcripts are in
    the corpus through Jul 14); only NEW meetings ingest going forward. Record schema:
    {source: "meeting-summary", chat: <slug>, date, who: "summary", sender: <participants>}.
  - Heartbeat: CloudWatch TwinMind/MeetingSummaryIngestRan (instance role). A dead-man alarm on
    this metric is created by infra (the old poller had NO alarm - that's why it rotted silently
    for 10 days). Md copies land in ~/twin-corpus/summaries-inbox/ for the Mac refresh to merge.

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

HOME = os.path.expanduser("~")
# SOLE-OWNER token family (2026-07-25, after the rotation death): this file belongs to the
# ingester ONLY. The gateway's granola MCP is removed; nothing else may read or refresh this
# family - refresh tokens rotate, and a second consumer kills the family within hours.
TOKEN_FILE = os.path.join(HOME, ".hermes", "mcp-tokens", "granola-ingest.json")
CLIENT_FILE = os.path.join(HOME, ".hermes", "mcp-tokens", "granola-ingest.client.json")
STATE = os.path.join(HOME, ".hermes", "state", "summary-ingest-state.json")
CORPUS = os.environ.get("TWIN_CORPUS", os.path.join(HOME, "twin-corpus"))
FTS_DB = os.path.join(CORPUS, "index", "corpus.db")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")
INBOX = os.path.join(CORPUS, "summaries-inbox")

MCP_URL = "https://mcp.granola.ai/mcp"
TOKEN_URL = "https://mcp-auth.granola.ai/oauth2/token"
EMBED_MODEL = "cohere.embed-multilingual-v3"


# ---------------------------------------------------------------- token
def load_token():
    tok = json.load(open(TOKEN_FILE))
    if tok.get("expires_at", 0) > time.time() + 60:
        return tok["access_token"]
    # expired: refresh and write back atomically. Properly urlencoded + the RFC-8707 `resource`
    # param (the authorize step pins the token to the MCP resource; refresh must match).
    client_id = json.load(open(CLIENT_FILE))["client_id"]
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
        "client_id": client_id,
        "resource": "https://mcp.granola.ai/mcp",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={
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
    print("token refreshed")
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
        # SSE frame(s): take the last data: line (the response message)
        data_lines = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")]
        raw = data_lines[-1] if data_lines else "{}"
    return (json.loads(raw) if raw.strip() else {}), sid


def mcp_connect(token):
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "twin-summary-ingest", "version": "1.0"}}}
    resp, sid = _post(token, init)
    if "error" in resp:
        raise RuntimeError(f"MCP initialize failed: {resp['error']}")
    try:  # notification; some servers 202 with empty body
        _post(token, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    except urllib.error.HTTPError:
        pass
    return sid


def mcp_call(token, sid, tool, args):
    payload = {"jsonrpc": "2.0", "id": int(time.time() * 1000) % 10**9,
               "method": "tools/call", "params": {"name": tool, "arguments": args}}
    resp, _ = _post(token, payload, sid)
    if "error" in resp:
        raise RuntimeError(f"{tool} error: {resp['error']}")
    content = resp.get("result", {}).get("content", [])
    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


# ---------------------------------------------------------------- parse + records
def parse_meetings(listing):
    """Extract (id, title, date-iso, participants) from the list_meetings XML-ish text."""
    out = []
    for m in re.finditer(
            r'<meeting id="([0-9a-f-]{36})" title="([^"]*)" date="([^"]*)">(.*?)</meeting>',
            listing, re.DOTALL):
        mid, title, date_raw, body = m.groups()
        pm = re.search(r"<known_participants>\s*(.*?)\s*</known_participants>", body, re.DOTALL)
        try:
            date_iso = datetime.strptime(
                re.sub(r"\s*GMT[+-]\d+", "", date_raw).strip(), "%b %d, %Y %I:%M %p"
            ).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            date_iso = date_raw
        out.append({"id": mid, "title": title.strip() or "Untitled meeting",
                    "date": date_iso, "participants": (pm.group(1).strip() if pm else "")})
    return out


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60] or "untitled"


def make_record(meeting, summary_text):
    day = meeting["date"][:10]
    ctx_text = f"[{meeting['title']} · {day}]\n{summary_text.strip()}"
    return {"source": "meeting-summary",
            "chat": f"{day}-{slugify(meeting['title'])}",
            "date": meeting["date"], "who": "summary",
            "sender": meeting["participants"][:200], "text": ctx_text}


# ---------------------------------------------------------------- index (INCREMENTAL ONLY)
def index_record(rec):
    import sqlite3
    import boto3
    import sqlite_vec
    # FTS: plain insert into the live table
    db = sqlite3.connect(FTS_DB)
    db.execute("INSERT INTO msgs VALUES (?,?,?,?,?,?)",
               (rec["source"], rec["chat"], rec["date"], rec["who"], rec["sender"], rec["text"]))
    db.commit(); db.close()
    # vectors: embed + append with fresh rowid (mirrors embed_corpus.embed_only)
    brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
    r = brt.invoke_model(modelId=EMBED_MODEL, body=json.dumps(
        {"texts": [rec["text"][:2048]], "input_type": "search_document", "truncate": "END"}))
    vec = json.loads(r["body"].read())["embeddings"][0]
    db = sqlite3.connect(VEC_DB)
    db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
    rid = db.execute("SELECT COALESCE(MAX(rowid),0)+1 FROM vec_meta").fetchone()[0]
    db.execute("INSERT INTO vec_meta VALUES (?,?,?,?,?,?,?)",
               (rid, rec["source"], rec["chat"], rec["date"], rec["who"], rec["sender"], rec["text"]))
    db.execute("INSERT INTO vec_idx(rowid, embedding) VALUES (?,?)",
               (rid, sqlite_vec.serialize_float32(vec)))
    db.commit(); db.close()


def heartbeat():
    try:
        import boto3
        boto3.client("cloudwatch", region_name="eu-west-1").put_metric_data(
            Namespace="TwinMind",
            MetricData=[{"MetricName": "MeetingSummaryIngestRan", "Value": 1}])
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
    meetings = parse_meetings(mcp_call(token, sid, "list_meetings", {"time_range": "last_30_days"}))
    print(f"granola MCP ok: {len(meetings)} meetings in window")
    if a.probe:
        for m in meetings[:5]:
            print(f"  {m['date'][:10]}  {m['title'][:60]}")
        return

    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    first_run = "_baseline" not in state

    if first_run:
        for m in meetings:
            state[m["id"]] = {"status": "baseline", "title": m["title"], "date": m["date"]}
        state["_baseline"] = datetime.now().astimezone().isoformat()
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump(state, open(STATE, "w"), indent=1)
        print(f"baseline: {len(meetings)} existing meetings marked seen (verbatim transcripts "
              "already cover them; no backfill)")
        heartbeat()
        return

    new = [m for m in meetings if m["id"] not in state]
    saved = failed = 0
    os.makedirs(INBOX, exist_ok=True)
    for m in new:
        try:
            detail = mcp_call(token, sid, "get_meetings", {"meeting_ids": [m["id"]]})
            if len(detail.strip()) < 40:
                print(f"summary empty for [{m['title'][:50]}] - retry next run")
                continue
            rec = make_record(m, detail)
            index_record(rec)
            with open(os.path.join(INBOX, f"{rec['chat']}.md"), "w", encoding="utf-8") as f:
                f.write(f"Meeting: {m['title']}\nDate: {m['date']}\n"
                        f"Participants: {m['participants']}\n(Granola AI summary, "
                        f"auto-ingested {datetime.now().strftime('%Y-%m-%d')}.)\n\n{detail.strip()}\n")
            state[m["id"]] = {"status": "saved", "title": m["title"], "date": m["date"],
                              "file": f"{rec['chat']}.md"}
            saved += 1
            print(f"ingested summary: {m['title'][:60]} ({m['date'][:10]})")
        except Exception as e:
            failed += 1
            state[m["id"]] = {"status": "failed", "title": m["title"], "err": str(e)[:150]}
            print(f"SUMMARY INGEST FAILED [{m['title'][:50]}]: {str(e)[:150]}")
    json.dump(state, open(STATE, "w"), indent=1)
    if saved or failed:
        print(f"summary ingest: saved={saved} failed={failed}")
    heartbeat()


if __name__ == "__main__":
    main()
