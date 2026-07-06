#!/usr/bin/env python3
"""Where is the money going? One terminal answer. Usage: python3 tools/costs.py [--days 7]"""
import argparse, base64, json, os, subprocess, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def env():
    for line in open(os.path.join(HERE, ".env")):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)

def bedrock_by_day(days):
    auth = base64.b64encode(f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()).decode()
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    out, page = defaultdict(float), 1
    while True:
        req = urllib.request.Request(
            f"https://cloud.langfuse.com/api/public/observations?type=GENERATION&fromStartTime={start}&limit=100&page={page}",
            headers={"Authorization": f"Basic {auth}"})
        d = json.load(urllib.request.urlopen(req))
        for o in d["data"]:
            u = o.get("usageDetails") or {}
            # Sonnet 4.6 Bedrock EU per MTok: in 3, cache-read 0.30, cache-write 3.75, out 15
            out[(o.get("startTime") or "")[:10]] += (u.get("input", 0) * 3 + u.get("cache_read_input_tokens", 0) * 0.30
                + u.get("cache_creation_input_tokens", 0) * 3.75 + u.get("output", 0) * 15) / 1e6
        if page >= d["meta"]["totalPages"]:
            break
        page += 1
    return dict(sorted(out.items()))

def aws_by_service():
    start = datetime.now(timezone.utc).strftime("%Y-%m-01")
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        r = subprocess.run(["aws", "ce", "get-cost-and-usage", "--time-period", f"Start={start},End={end}",
                            "--granularity", "MONTHLY", "--metrics", "UnblendedCost",
                            "--group-by", "Type=DIMENSION,Key=SERVICE",
                            "--filter", '{"Not":{"Dimensions":{"Key":"RECORD_TYPE","Values":["Credit","Refund"]}}}'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        groups = json.loads(r.stdout)["ResultsByTime"][0]["Groups"]
        svc = {g["Keys"][0]: float(g["Metrics"]["UnblendedCost"]["Amount"]) for g in groups}
        return dict(sorted(((k, v) for k, v in svc.items() if v >= 0.01), key=lambda x: -x[1]))
    except Exception:
        return None

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    env()
    print("== Bedrock tokens by day (from traces; the ~only real cost) ==")
    days = bedrock_by_day(args.days)
    for d, c in days.items():
        print(f"  {d}  ${c:.2f}")
    print(f"  {args.days}-day total: ${sum(days.values()):.2f}  (untraced embeddings add ~cents/run)")
    print("== AWS month-to-date by service (gross, credits excluded) ==")
    svc = aws_by_service()
    if svc is None:
        print("  (aws session expired - run 'aws login' in Terminal for this half)")
    else:
        for k, v in svc.items():
            print(f"  {k}: ${v:.2f}")
    print("== Fixed facts ==")
    print("  EC2 instance: $0 (free trial until Dec 2026) | EBS disk: ~$2-3/mo | alarm+SNS: ~$0.10/mo")
    print("  Wallet charge: $0 - everything draws from credits (balance: console > Billing > Credits)")
