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
    "teacher_shadow": """Score section '4. ONE TECHNICAL THING' 0-1 on: plain words without losing depth;
quotes REAL code with a file path; ends with quiz question AND its answer. Return JSON {"score":0-1,"why":"<15 words"}""",
    "coach_shadow": """Score section '5. COACH' 0-1 on: cites a concrete fact from Daniel's actual life/data
(not generic); connects to his stated values (curious, adventurous, determined, best version); zero platitudes.
Return JSON {"score":0-1,"why":"<15 words"}""",
}

brt = boto3.client("bedrock-runtime", region_name="eu-west-1")
body = todays_brief()
auth = base64.b64encode(f"{os.environ['HERMES_LANGFUSE_PUBLIC_KEY']}:{os.environ['HERMES_LANGFUSE_SECRET_KEY']}".encode()).decode()
for name, rubric in RUBRICS.items():
    r = brt.converse(modelId="eu.anthropic.claude-sonnet-4-6",
        system=[{"text": rubric}], messages=[{"role": "user", "content": [{"text": body[:6000]}]}],
        inferenceConfig={"maxTokens": 150, "temperature": 0})
    txt = r["output"]["message"]["content"][0]["text"]
    try:
        v = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
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
