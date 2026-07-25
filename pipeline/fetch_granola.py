#!/usr/bin/env python3
"""fetch_granola.py - Mac-side Granola transcript ingester (spec 2026-07-14).

The post-call mirror of background-prep's pre-call poller: every 15 min, list
Granola documents, and for any NEW meeting whose transcript has finalized, save
the EXACT verbatim transcript as one Markdown file in the corpus, then normalize
+ reindex so the twin knows the meeting within minutes. Fully deterministic, no
LLM in the ingestion path.

Auth is Path 2 (proven, fully local, no Claude, no per-run cost):
  Keychain "Granola Safe Storage"/"Granola Key"
    -> Electron safeStorage AES-128-CBC (PBKDF2-SHA1(pw,"saltysalt",1003,16), IV=16x0x20)
    -> decrypt storage.dek (strip "v10") -> base64 -> 32-byte DEK
    -> AES-256-GCM(DEK) over supabase.json.enc [12B IV][ct][16B tag] -> live token JSON
    -> workos_tokens.access_token (Bearer) -> REST API.
Secrets live in memory only. Nothing sensitive is ever printed or written to disk.

Design rulings (spec open questions, resolved):
  Q1 host/scheduler: Mac launchd. Path 2 needs the login Keychain, and the corpus
     lives on the Mac. (Box + MCP is Path 3, the break-glass fallback only.)
  Q2 speaker labels: strict Me:/Them: (all the normalizer understands today).
     source "microphone" -> Me, everything else -> Them. detected_speaker_name deferred.
  Q3 "final" heuristic: segments exist AND the tail segment is_final is truthy. A
     still-transcribing meeting has a non-final tail -> stays pending -> re-checked
     next poll. No file is half-written.
  Q4 reindex: normalize + build_index (FTS, free, local, deterministic) inline so the
     meeting is keyword-searchable within minutes. The Bedrock embedding step is NOT
     run per poll (it rebuilds the whole vectors.db over the network and costs money -
     a 15-min-poller cost trap); vectors catch up on the existing weekly Mac->box
     refresh. See DEVIATION note in the repo report.

Scope (Daniel's ruling): only NEW meetings going forward. First run marks every
current document as baseline (no file written, never backfilled).

Silent when healthy. Prints only actions and problems. Any transcript that fails
to fetch or parse is counted and printed - never silently dropped.
"""
import base64
import fcntl
import gzip
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from hashlib import pbkdf2_hmac

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HOME = os.path.expanduser("~")
GRANOLA = os.path.join(HOME, "Library", "Application Support", "Granola")
DEK_FILE = os.path.join(GRANOLA, "storage.dek")
ENC_FILE = os.path.join(GRANOLA, "supabase.json.enc")

STATE_DIR = os.path.join(HOME, ".hermes", "state")
STATE = os.path.join(STATE_DIR, "transcript-state.json")
HEARTBEAT_FILE = os.path.join(STATE_DIR, "transcript-poller-heartbeat.txt")
REINDEX_LOCK = os.path.join(STATE_DIR, "corpus-reindex.lock")

INBOX_DIR = os.path.join(HOME, "twin-corpus", "raw", "transcripts-inbox")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE = "https://api.granola.ai"
CLIENT_VERSION = "7.394.3"
DOC_LIMIT = 100  # newest-first window; comfortably covers the ~21 existing + all going forward


# ----------------------------------------------------------------------------
# Auth chain (network + Keychain; lifted verbatim from the proven granola_path2_decrypt.py)
# ----------------------------------------------------------------------------
def keychain_password():
    r = subprocess.run(
        ["security", "find-generic-password", "-w",
         "-s", "Granola Safe Storage", "-a", "Granola Key"],
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"keychain read failed: {r.stderr.strip()[:120]}")
    return r.stdout.strip()


def safestorage_decrypt(blob, pw):
    assert blob[:3] == b"v10", f"unexpected safeStorage prefix {blob[:3]!r}"
    key = pbkdf2_hmac("sha1", pw.encode("utf-8"), b"saltysalt", 1003, 16)
    dec = Cipher(algorithms.AES(key), modes.CBC(b"\x20" * 16)).decryptor()
    pt = dec.update(blob[3:]) + dec.finalize()
    return pt[:-pt[-1]]  # strip PKCS7 padding


def get_dek(pw):
    raw = safestorage_decrypt(open(DEK_FILE, "rb").read(), pw)
    dek = base64.b64decode(raw)
    assert len(dek) == 32, f"DEK is {len(dek)} bytes, expected 32"
    return dek


def decrypt_enc(dek):
    blob = open(ENC_FILE, "rb").read()
    iv, ct, tag = blob[:12], blob[12:-16], blob[-16:]
    pt = AESGCM(dek).decrypt(iv, ct + tag, None)
    return json.loads(pt)


def get_token():
    """Full Path-2 chain -> live Bearer access token. Any failure here means the
    local decrypt broke (Granola update) or the Keychain is unreadable - the SCREAM
    case, handled by main()."""
    data = decrypt_enc(get_dek(keychain_password()))
    wt = data.get("workos_tokens")
    wt = json.loads(wt) if isinstance(wt, str) else wt
    if not wt or "access_token" not in wt:
        raise RuntimeError("decrypted token JSON missing workos_tokens.access_token")
    return wt["access_token"]


def api(path, token, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST")
    for h, v in {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": f"Granola/{CLIENT_VERSION} Electron",
                 "X-Client-Version": CLIENT_VERSION}.items():
        req.add_header(h, v)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode())


def fetch_documents(token, limit=DOC_LIMIT):
    data = api("/v2/get-documents", token, {"limit": limit})
    return data.get("docs") or data.get("documents") or []


def fetch_transcript(token, document_id):
    return api("/v1/get-document-transcript", token, {"document_id": document_id})


# ----------------------------------------------------------------------------
# Pure logic (no network, no Keychain, no secrets - the test surface)
# ----------------------------------------------------------------------------
def doc_id(doc):
    return doc.get("id") or doc.get("document_id")


def doc_title(doc):
    return (doc.get("title") or doc.get("name") or "Untitled meeting").strip() or "Untitled meeting"


def doc_updated_ts(doc):
    """Best-effort 'last changed' marker for update detection. Granola may name it
    any of these; if none is present we fall back to created_at, so update detection
    degrades gracefully to 'new-only' rather than crashing on an unknown schema."""
    for k in ("updated_at", "last_updated_at", "updated", "modified_at", "created_at"):
        if doc.get(k):
            return str(doc[k])
    return ""


def _ts_gt(a, b):
    """a strictly later than b, robust to epoch numbers or ISO-8601 strings."""
    try:
        return float(a) > float(b)
    except (TypeError, ValueError):
        return str(a) > str(b)


def _parse_created(doc):
    raw = doc.get("created_at") or doc.get("created") or ""
    try:
        s = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        try:
            return datetime.fromtimestamp(float(raw), timezone.utc)
        except (TypeError, ValueError):
            return None


def doc_created_ymd(doc):
    dt = _parse_created(doc)
    return (dt or datetime.now()).strftime("%Y-%m-%d")


def doc_created_human(doc):
    dt = _parse_created(doc)
    dt = dt or datetime.now()
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s[:60] or "untitled"


def map_speaker(source):
    """microphone = Daniel's mic -> Me; everything else (system audio / other party) -> Them."""
    return "Me" if (source or "").lower() == "microphone" else "Them"


def normalize_segments(raw):
    """Coerce the transcript payload into a list of segment dicts, or raise so the
    caller counts it as a parse failure instead of silently writing an empty file."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        segs = raw.get("transcript") or raw.get("segments")
        if isinstance(segs, list):
            return segs
    raise ValueError(f"unrecognized transcript payload: {type(raw).__name__}")


def is_final_transcript(segments):
    """Final = at least one segment AND the tail segment is marked is_final. A meeting
    still being transcribed has a non-final interim tail, so it stays pending."""
    return bool(segments) and bool(segments[-1].get("is_final"))


def segments_to_body(segments):
    """Collapse consecutive same-source segments into one Me:/Them: turn (matches
    Granola's own export and reads better)."""
    turns, who, buf = [], None, []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        w = map_speaker(seg.get("source"))
        if w != who:
            if buf:
                turns.append(f"{who}: {' '.join(buf)}")
            who, buf = w, [text]
        else:
            buf.append(text)
    if buf:
        turns.append(f"{who}: {' '.join(buf)}")
    return "\n".join(turns)


def participants(doc):
    names = []
    people = doc.get("people") or doc.get("attendees") or []
    if isinstance(doc.get("google_calendar_event"), dict):
        people = people or doc["google_calendar_event"].get("attendees") or []
    for p in people if isinstance(people, list) else []:
        if isinstance(p, dict):
            n = p.get("name") or p.get("displayName") or p.get("email")
        else:
            n = str(p)
        if n and n not in names:
            names.append(n)
    return ", ".join(names) if names else "(unknown)"


def build_markdown(doc, segments, saved_on):
    body = segments_to_body(segments)
    # saved_on may be a date/datetime OR a string (a manual fetch on 2026-07-15 passed
    # an isoformat string and hit 'str has no attribute strftime'). Accept both.
    stamp = saved_on.strftime("%Y-%m-%d") if hasattr(saved_on, "strftime") else str(saved_on)[:10]
    return (
        f"Meeting Title: {doc_title(doc)}\n"
        f"Date: {doc_created_human(doc)}\n"
        f"Participants: {participants(doc)}\n"
        f"(Exact Granola transcript, auto-saved {stamp}.)\n"
        f"\n"
        f"{body}\n"
    )


def classify(doc, state):
    """What to do with one doc given prior state:
      new    - never seen -> fetch + save if final
      update - previously saved and its updated-timestamp advanced -> re-fetch + overwrite
      retry  - previous fetch failed -> try again
      skip   - unchanged saved, or a baselined pre-existing meeting (frozen: no backfill)
    """
    did = doc_id(doc)
    rec = state.get(did)
    if rec is None:
        return "new"
    status = rec.get("status")
    if status == "baseline":
        return "skip"  # pre-existing meeting, deliberately never backfilled (Daniel's scope ruling)
    if status == "failed":
        return "retry"
    if status == "saved":
        return "update" if _ts_gt(doc_updated_ts(doc), rec.get("updated", "")) else "skip"
    return "skip"


def dedupe_name(inbox_dir, base):
    """Filename that does not collide with a DIFFERENT meeting already in the inbox.
    Updates to the same meeting reuse the stored name, so this only fires on genuine
    slug clashes between distinct meetings on the same day."""
    name = f"{base}.md"
    n = 2
    while os.path.exists(os.path.join(inbox_dir, name)):
        name = f"{base}-{n}.md"
        n += 1
    return name


def process(docs, fetch_transcript_fn, state, inbox_dir, now, first_run):
    """Core orchestrator. fetch_transcript_fn(document_id) -> raw transcript payload
    is the injected boundary: real runs pass a Granola-backed fetch, tests pass a
    fake so nothing touches the network or the Keychain. Mutates `state` in place;
    returns honest counters."""
    c = {"saved": 0, "updated": 0, "failed": 0, "pending": 0, "baseline": 0, "skipped": 0}

    if first_run:
        for d in docs:
            did = doc_id(d)
            if not did:
                continue
            state[did] = {"status": "baseline", "ts": now.isoformat(),
                          "updated": doc_updated_ts(d), "meeting": doc_title(d)}
            c["baseline"] += 1
        state["_baseline"] = now.isoformat()
        return c

    for d in docs:
        did = doc_id(d)
        if not did:
            continue
        action = classify(d, state)
        if action == "skip":
            c["skipped"] += 1
            continue

        try:
            segs = normalize_segments(fetch_transcript_fn(did))
        except Exception as e:  # fetch error OR unparseable payload - counted, never hidden
            prev = state.get(did, {})
            state[did] = {"status": "failed", "ts": now.isoformat(),
                          "updated": doc_updated_ts(d), "meeting": doc_title(d),
                          "err": str(e)[:120], "file": prev.get("file")}
            c["failed"] += 1
            print(f"TRANSCRIPT FAILED [{doc_title(d)[:50]}] ({did}): {str(e)[:120]}")
            continue

        if not is_final_transcript(segs):
            c["pending"] += 1  # still transcribing; re-check next poll, leave state as-is
            continue

        try:
            md = build_markdown(d, segs, now)
        except Exception as e:
            state[did] = {"status": "failed", "ts": now.isoformat(),
                          "updated": doc_updated_ts(d), "meeting": doc_title(d),
                          "err": str(e)[:120], "file": state.get(did, {}).get("file")}
            c["failed"] += 1
            print(f"TRANSCRIPT PARSE FAILED [{doc_title(d)[:50]}] ({did}): {str(e)[:120]}")
            continue

        fname = (state.get(did) or {}).get("file") or dedupe_name(
            inbox_dir, f"{doc_created_ymd(d)}-{slugify(doc_title(d))}")
        with open(os.path.join(inbox_dir, fname), "w", encoding="utf-8") as f:
            f.write(md)
        state[did] = {"status": "saved", "ts": now.isoformat(),
                      "updated": doc_updated_ts(d), "meeting": doc_title(d), "file": fname}
        c["updated" if action == "update" else "saved"] += 1

    return c


# ----------------------------------------------------------------------------
# State + heartbeat + reindex (I/O, but no secrets)
# ----------------------------------------------------------------------------
def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump(state, open(STATE, "w"), indent=1)


def heartbeat(now):
    """Dead-man coverage two ways. Local timestamp file is authoritative Mac-side
    (the weekly review checks its staleness). CloudWatch is best-effort for the box
    alarm path and simply no-ops if this Mac has no AWS creds or is offline."""
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(now.isoformat())
    except Exception:
        pass
    try:
        subprocess.run(["aws", "cloudwatch", "put-metric-data", "--namespace", "TwinMind",
                        "--metric-name", "TranscriptPollerRan", "--value", "1",
                        "--region", "eu-west-1"], capture_output=True, timeout=30)
    except Exception:
        pass


def inbox_newer_than_index():
    """True if any saved transcript is newer than the FTS index. This makes ingest fire for
    a meeting added OUTSIDE this poller's own save path too (a manual fetch, a restored file) -
    so the guarantee is 'whenever a transcript is saved it gets ingested', not just on poller saves."""
    idx = os.path.join(HOME, "twin-corpus", "index", "corpus.db")
    if not os.path.isdir(INBOX_DIR):
        return False
    idx_mtime = os.path.getmtime(idx) if os.path.exists(idx) else 0.0
    return any(f.endswith(".md") and os.path.getmtime(os.path.join(INBOX_DIR, f)) > idx_mtime
               for f in os.listdir(INBOX_DIR))


def reindex(python_exe):
    """normalize -> build FTS index, under a non-blocking lock so it never overlaps a
    manual corpus refresh. If the lock is held, the just-written files stay in the
    inbox and get indexed on the next poll (or by the refresh in progress)."""
    os.makedirs(STATE_DIR, exist_ok=True)
    lockf = open(REINDEX_LOCK, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("reindex skipped: corpus refresh lock held; new transcripts index next poll")
        lockf.close()
        return False
    try:
        for script in ("normalize_transcripts.py", "build_index.py"):
            r = subprocess.run([python_exe, os.path.join(REPO_ROOT, "pipeline", script)],
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                print(f"REINDEX FAILED at {script}: {r.stderr.strip()[:200]}")
                return False
        return True
    finally:
        fcntl.flock(lockf, fcntl.LOCK_UN)
        lockf.close()


def main():
    now = datetime.now().astimezone()
    state = load_state()
    first_run = "_baseline" not in state

    try:
        token = get_token()
    except Exception as e:
        # decrypt/Keychain failure = ingestion is broken (Granola updated, or ACL revoked).
        # SCREAM: print loudly and do NOT heartbeat, so the dead-man staleness alarm fires.
        msg = f"GRANOLA DECRYPT/KEYCHAIN FAILED (ingestion stopped): {str(e)[:200]}"
        print(msg, file=sys.stderr)
        print(msg)
        sys.exit(1)

    try:
        docs = fetch_documents(token)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # stale token = Granola app has not run/refreshed. Soft state, not a crash.
            print("granola token stale (app not running?) - HTTP 401, retry next poll")
            heartbeat(now)
            return
        raise

    os.makedirs(INBOX_DIR, exist_ok=True)
    c = process(docs, lambda did: fetch_transcript(token, did), state, INBOX_DIR, now, first_run)
    save_state(state)

    if not first_run and (c["saved"] or c["updated"] or inbox_newer_than_index()):
        reindex(sys.executable)

    if first_run:
        print(f"granola baseline seeded: {c['baseline']} existing meetings marked seen (no backfill)")
    elif c["saved"] or c["updated"] or c["failed"]:
        print(f"granola ingest: saved={c['saved']} updated={c['updated']} failed={c['failed']}")

    heartbeat(now)


if __name__ == "__main__":
    main()
