#!/usr/bin/env python3
"""SHADOW-MODE judges (stepback 2026-07-14: build now, trust after calibration).
Scores today's brief on teacher + coach rubrics; writes scores to Langfuse tagged
shadow=true. NOT used for any decision until agreement vs Daniel's verdicts >= threshold.
Run nightly: hermes venv python (boto3 + langfuse creds from ~/.hermes/.env)."""
import base64, email, imaplib, json, os, re, urllib.request
import boto3

for line in open(os.path.expanduser("~/.hermes/.env")):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1); os.environ.setdefault(k, v)

def todays_brief():
    with imaplib.IMAP4_SSL("imap.gmail.com") as im:
        im.login(os.environ["TWIN_SMTP_ADDRESS"], os.environ["TWIN_SMTP_APP_PASSWORD"])
        im.select('"[Gmail]/All Mail"', readonly=True)
        ok, d = im.search(None, '(SUBJECT "Morning brief")')
        ok, raw = im.fetch(d[0].split()[-1], "(BODY.PEEK[])")
        msg = email.message_from_bytes(raw[0][1])
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode("utf-8", "replace")
    return ""

RUBRICS = {
    "teacher_shadow": """You are a strict, fair judge of the morning brief's teaching section.
Score section '4. ONE TECHNICAL THING' 0-1 on: plain words without losing depth; quotes REAL code with a file path; ends with a quiz question AND its answer.
<calibration_examples>
GOOD (~0.9): explains RRF ranking mechanics grounded in a real file path, ends with a quiz and its answer.
BAD (~0.3): teaches scalable-oversight well, but has NO answer line after the quiz and cites a stale item-count. (missing the required answer + an ungrounded number)
</calibration_examples>
Reason FIRST from the specific evidence, THEN score. Return JSON only: {"reasoning":"<1-2 sentences citing what you saw>","score":0-1}""",
    "coach_shadow": """You are a strict, fair judge of the morning brief's coach section.
Score section '5. COACH' 0-1 on: cites a concrete fact from Daniel's actual life/data (not generic); connects to his stated values (curious, adventurous, determined, best version); zero platitudes.
<calibration_examples>
GOOD (~0.9): anchors to a specific thing Daniel actually did and ties it to a concrete next step. (real fact, no platitude)
BAD (~0.3): well-written but pushes action on a stale premise, e.g. a call that already happened. (built on a fact no longer true)
</calibration_examples>
Reason FIRST from the specific evidence, THEN score. Return JSON only: {"reasoning":"<1-2 sentences citing what you saw>","score":0-1}""",
}

brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
body = todays_brief()
auth = base64.b64encode(f"{os.environ['HERMES_LANGFUSE_PUBLIC_KEY']}:{os.environ['HERMES_LANGFUSE_SECRET_KEY']}".encode()).decode()
for name, rubric in RUBRICS.items():
    r = brt.converse(modelId="eu.anthropic.claude-sonnet-4-6",
        system=[{"text": rubric}], messages=[{"role": "user", "content": [{"text": body[:6000]}]}],
        inferenceConfig={"maxTokens": 300, "temperature": 0})
    txt = r["output"]["message"]["content"][0]["text"]
    try:
        v = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        v["why"] = v.get("reasoning", v.get("why", ""))  # reason-first schema; keep downstream key
    except Exception:
        v = {"score": -1, "why": "judge parse error"}
    req = urllib.request.Request("https://cloud.langfuse.com/api/public/scores",
        data=json.dumps({"name": name, "value": v["score"], "comment": v["why"],
                         "traceId": None, "id": None}).encode() if False else json.dumps({
            "name": name, "value": v["score"], "comment": f"shadow | {v['why']}"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"})
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"{name}: score={v['score']} (langfuse write failed: {e})")
        continue
    print(f"{name}: {v['score']} - {v['why']}")
