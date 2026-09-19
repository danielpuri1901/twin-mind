# Phase 0: Hermes Twin on AWS - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A locked-down Hermes agent on AWS that Daniel talks to on Discord, powered by Bedrock Claude, reading a deployed working set of his corpus, with budget guardrails and a scorecard started.

**Architecture:** Mac stays the corpus factory (raw -> normalized -> wiki + FTS index). A t4g.small EC2 box (no inbound ports, SSM-only access, encrypted EBS) runs Hermes as a systemd service; Discord and Bedrock are outbound connections. The derived working set syncs point-to-point to the box; raw data never leaves the Mac.

**Tech Stack:** AWS CLI v2, EC2 t4g.small (AL2023 arm64), SSM Session Manager, Bedrock (Claude via global endpoint), Hermes Agent (installer + systemd), SQLite FTS5, Discord bot, Langfuse Cloud free tier.

## Global Constraints

- Ground every AWS decision in official docs; never invent flags, prices, or limits (project CLAUDE.md).
- Corpus two-tier: raw stays on the Mac, encrypted; only the derived working set (wiki/, corpus.db, normalized comms) deploys to the box's encrypted EBS. Nothing corpus-related ever goes to S3, git remotes, or third-party storage.
- Models: Haiku 4.5 triage, Sonnet 4.6 drafting, Opus rare hard reasoning. **EU geo inference profiles** (`eu.anthropic.claude-sonnet-4-6`, Haiku 4.5 EU profile ID confirmed via discovery) - keeps personal-data processing in-geo per the Bedrock geographic-CRIS doc. Home region **eu-west-1**.
- Bedrock path has NO Hermes-emitted prompt caching (Hermes only sets cache breakpoints on native Anthropic/OpenRouter/Portal). Measure real burn via Langfuse before trusting any cost estimate.
- **Execution order (revised after cold review): Tasks 1-7 Mac-local first, then a local Hermes validation gate (Task 7b), then and only then Tasks 8-13 (AWS box).**
- Hermes lockdown at launch: `approvals.mode: manual`, `cron_mode: deny`, terminal backend `docker`, Discord user allowlist = Daniel only.
- Cost: budget alert before any resource exists. No idle managed services. t4g.small free-trial 750 hrs/mo through Dec 31 2026 (verified on aws.amazon.com/ec2/instance-types/t4).
- No em dashes in any authored text. Long markdown: one sentence per line.
- Commits: no auto co-author.

## User-interactive gates (Daniel must do these personally)

- G1: `! aws login` browser auth after CLI install (Task 2).
- G2: Bedrock Anthropic use-case form in the console, one time (Task 4).
- G3: Discord bot creation in the Discord developer portal (Task 8).
- G4: Langfuse Cloud account creation (Task 10).

---

### Task 1: Project scaffold commit

**Files:**
- Modify: `/Users/you/twin-mind/` (repo already init'd; README, CLAUDE.md, docs/, tools/ exist)

**Interfaces:**
- Produces: a clean baseline commit so every later task is a reviewable diff.

- [ ] **Step 1: Commit the scaffold**

```bash
cd "/Users/you/twin-mind"
git add -A
git commit -m "chore: project scaffold - design doc, plans, ingestion tools, project rules"
```

- [ ] **Step 2: Verify clean tree**

Run: `git status --short` -> expected: empty output.

---

### Task 2: AWS CLI + credentials

**Files:** none (system install)

**Interfaces:**
- Produces: working `aws` CLI with short-term credentials and default region `us-east-1`. Every later task consumes this.

- [ ] **Step 1: Install CLI**

```bash
brew install awscli
aws --version   # expect aws-cli/2.x
```

(Official pkg installer at docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html is the alternative; brew ships the same official CLI and matches existing tooling maintenance.)

- [ ] **Step 2 (G1, Daniel): authenticate**

Daniel runs `! aws login` and completes the browser flow.
This is the auth doc's top-recommended option (short-term credentials, no long-lived keys on disk).
Fallback if `aws login` is unavailable on this CLI version: `aws configure sso` per docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html.

- [ ] **Step 3: Set region + verify identity**

```bash
aws configure set region us-east-1
aws sts get-caller-identity   # expect JSON with Account + Arn
```

---

### Task 3: Budget guardrail (before any resource)

**Files:**
- Create: `infra/budget.json`

**Interfaces:**
- Produces: monthly cost budget with email alerts at 50%/80%/100% of $50.

- [ ] **Step 1: Write budget config**

```json
{
  "BudgetName": "twin-mind-monthly",
  "BudgetLimit": { "Amount": "50", "Unit": "USD" },
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST",
  "CostTypes": { "IncludeCredit": false, "IncludeRefund": false }
}
```

- [ ] **Step 2: Create budget + notifications**

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
aws budgets create-budget --account-id "$ACCOUNT" \
  --budget file://infra/budget.json \
  --notifications-with-subscribers '[
    {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":50,"ThresholdType":"PERCENTAGE"},
     "Subscribers":[{"SubscriptionType":"EMAIL","Address":"you@example.com"}]},
    {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},
     "Subscribers":[{"SubscriptionType":"EMAIL","Address":"you@example.com"}]},
    {"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":100,"ThresholdType":"PERCENTAGE"},
     "Subscribers":[{"SubscriptionType":"EMAIL","Address":"you@example.com"}]}]'
```

- [ ] **Step 3: Verify**

Run: `aws budgets describe-budgets --account-id "$ACCOUNT"` -> expect `twin-mind-monthly`.

- [ ] **Step 4: Commit** `git add infra/budget.json && git commit -m "infra: monthly budget guardrail"`

---

### Task 4: Bedrock model access

**Interfaces:**
- Produces: invokable Claude models; model IDs consumed by Hermes config (Task 9).

- [ ] **Step 1 (G2, Daniel): submit Anthropic use-case form**

Console -> Bedrock (`us-east-1`) -> Model catalog -> any Anthropic model -> submit use-case details.
One time per account (docs.aws.amazon.com/bedrock/latest/userguide/model-access.html).

- [ ] **Step 2: Verify programmatic access with a real call**

```bash
# discover the real EU inference-profile IDs (deterministic, no guessing)
aws bedrock list-inference-profiles --region eu-west-1 \
  --query 'inferenceProfileSummaries[?contains(inferenceProfileId, `anthropic`)].inferenceProfileId'
# then smoke-test with the discovered Haiku EU ID:
aws bedrock-runtime converse --region eu-west-1 \
  --model-id "eu.anthropic.claude-haiku-4-5-20251001-v1:0" \
  --messages '[{"role":"user","content":[{"text":"Reply with exactly: pong"}]}]' \
  --query 'output.message.content[0].text'
```

Expected: `"pong"`. If AccessDenied: re-check form status on the Model access page.
Note: the one-time Anthropic use-case form is submitted in `us-east-1`/`us-west-2` per the model-access doc and applies account-wide; the runtime region stays eu-west-1. Use the exact IDs the discovery command returns (Sonnet: `eu.anthropic.claude-sonnet-4-6`).

---

### Task 5: FTS index over the corpus

**Files:**
- Create: `tools/build_index.py`
- Test: `tools/test_build_index.py`

**Interfaces:**
- Consumes: `~/twin-corpus/normalized/*.jsonl` (records `{source, date, who, text, ...}`).
- Produces: `~/twin-corpus/index/corpus.db` with FTS5 table `msgs(source, chat, date, who, sender, text)` and CLI `python3 tools/build_index.py [--query "term"]`.

- [ ] **Step 1: Write failing test**

```python
# tools/test_build_index.py
import json, os, sqlite3, subprocess, sys, tempfile

def test_build_and_search():
    with tempfile.TemporaryDirectory() as td:
        norm = os.path.join(td, "normalized"); os.makedirs(norm)
        rec = {"source": "imessage", "chat": "c1", "date": "2026-01-01T10:00:00",
               "who": "me", "sender": "Me", "text": "gurobi presolve trick"}
        with open(os.path.join(norm, "x.jsonl"), "w") as f:
            f.write(json.dumps(rec) + "\n")
        env = dict(os.environ, TWIN_CORPUS=td)
        subprocess.run([sys.executable, "tools/build_index.py"], check=True, env=env)
        db = sqlite3.connect(os.path.join(td, "index", "corpus.db"))
        rows = db.execute("SELECT text FROM msgs WHERE msgs MATCH 'gurobi'").fetchall()
        assert rows == [("gurobi presolve trick",)]

if __name__ == "__main__":
    test_build_and_search(); print("ok")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 tools/test_build_index.py` -> expected: FileNotFoundError / CalledProcessError (script missing).

- [ ] **Step 3: Implement**

```python
#!/usr/bin/env python3
# tools/build_index.py - build SQLite FTS5 index over normalized corpus records.
import glob, json, os, sqlite3, sys

ROOT = os.environ.get("TWIN_CORPUS", os.path.expanduser("~/twin-corpus"))
DB = os.path.join(ROOT, "index", "corpus.db")

def build():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("DROP TABLE IF EXISTS msgs")
    db.execute("CREATE VIRTUAL TABLE msgs USING fts5(source, chat, date, who, sender, text)")
    n = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "normalized", "*.jsonl"))):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            db.execute("INSERT INTO msgs VALUES (?,?,?,?,?,?)",
                       (r.get("source", ""), r.get("chat", r.get("meeting", "")),
                        r.get("date", ""), r.get("who", ""), r.get("sender", ""),
                        r.get("text", "")))
            n += 1
    db.commit()
    print(f"indexed {n} records -> {DB}")

def query(term):
    db = sqlite3.connect(DB)
    for row in db.execute(
            "SELECT date, source, who, snippet(msgs, 5, '[', ']', '...', 12) "
            "FROM msgs WHERE msgs MATCH ? ORDER BY date LIMIT 20", (term,)):
        print(" | ".join(str(c) for c in row))

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--query":
        query(sys.argv[2])
    else:
        build()
```

- [ ] **Step 4: Test passes + real build**

Run: `python3 tools/test_build_index.py` -> `ok`.
Run: `python3 tools/build_index.py` -> expect `indexed ~27000 records` (20,583 iMessage + 6,558 transcript turns).
Spot check: `python3 tools/build_index.py --query "Routes AI"` returns real rows.

- [ ] **Step 5: Commit** `git add tools/build_index.py tools/test_build_index.py && git commit -m "feat: FTS5 corpus index + query CLI"`

---

### Task 6: Wiki compile v1 (Karpathy pattern, run on Max sub)

**Files:**
- Create: `tools/compile_wiki_prompt.md` (the compile instruction), output in `~/twin-corpus/wiki/`

**Interfaces:**
- Consumes: `normalized/*.jsonl`, `build_index.py --query`.
- Produces: `wiki/index.md`, `wiki/voice-profile.md`, `wiki/people/<name>.md`, `wiki/topics/<topic>.md`. Deployed in Task 11; referenced by the corpus skill (Task 12).

- [ ] **Step 1: Write the compile prompt**

```markdown
# compile_wiki_prompt.md
You are compiling Daniel's personal wiki from ~/twin-corpus/normalized/*.jsonl.
Rules: the wiki is LLM-maintained; cite evidence as source+date on every claim;
never invent facts; one sentence per line; link related pages with [[name]].
Produce/refresh:
1. wiki/voice-profile.md - how Daniel writes (msg length, tone, phrases he
   actually uses, emoji habits, sign-offs) and how he speaks (filler words,
   rambling patterns from transcripts). Quote 10+ short real examples, cited.
2. wiki/people/<slug>.md for the 10 most frequent contacts - relationship,
   tone Daniel uses with them, running topics, last contact date.
3. wiki/topics/<slug>.md for recurring topics (job search, Routes AI, thesis,
   training, family) - state of play, decisions made, open loops.
4. wiki/index.md - one-line description + link for every page.
Work incrementally: read existing pages first, update rather than rewrite.
```

- [ ] **Step 2: Run the compile in Claude Code (Max sub, $0 marginal)**

In a fresh Claude Code session in `~/twin-corpus/`: paste the prompt file content and let it work through the corpus (it may use `build_index.py --query` for lookups).

- [ ] **Step 3: Verify**

`ls ~/twin-corpus/wiki/` -> `index.md voice-profile.md people/ topics/` all present; every page cites sources; `index.md` links resolve.

- [ ] **Step 4: Commit the prompt (not the wiki - corpus is never committed)**

```bash
git add tools/compile_wiki_prompt.md && git commit -m "feat: wiki compile prompt v1"
```

---

### Task 7: Scorecard v0 from iMessage pairs

**Files:**
- Create: `tools/extract_pairs.py`
- Output: `~/twin-corpus/index/scorecard-pairs.jsonl` (never committed)

**Interfaces:**
- Consumes: `normalized/imessage.jsonl`.
- Produces: candidate `{context: [...], inbound, reply}` pairs; Daniel curates 20 gold ones. Consumed later by the Langfuse dataset (Task 13).

- [ ] **Step 1: Implement extractor**

```python
#!/usr/bin/env python3
# tools/extract_pairs.py - inbound -> Daniel's actual reply pairs for the scorecard.
import json, os
from datetime import datetime, timedelta

SRC = os.path.expanduser("~/twin-corpus/normalized/imessage.jsonl")
OUT = os.path.expanduser("~/twin-corpus/index/scorecard-pairs.jsonl")

recs = [json.loads(l) for l in open(SRC)]
by_chat = {}
for r in recs:
    by_chat.setdefault(r["chat"], []).append(r)

pairs = []
for chat, msgs in by_chat.items():
    msgs.sort(key=lambda r: r["date"])
    for i, m in enumerate(msgs):
        if m["who"] != "me" or i == 0 or msgs[i-1]["who"] != "them":
            continue
        gap = datetime.fromisoformat(m["date"]) - datetime.fromisoformat(msgs[i-1]["date"])
        if gap > timedelta(hours=12) or len(m["text"]) < 25:
            continue
        pairs.append({"chat": chat,
                      "context": [f'{x["who"]}: {x["text"]}' for x in msgs[max(0, i-6):i-1]],
                      "inbound": msgs[i-1]["text"], "reply": m["text"], "date": m["date"]})

# Stratified sample: round-robin across contacts and reply-length buckets,
# so the gold set reflects texting-Daniel AND essay-Daniel, not just longest replies.
def bucket(p):
    n = len(p["reply"])
    return "short" if n < 80 else "medium" if n < 200 else "long"

groups = {}
for p in pairs:
    groups.setdefault((p["chat"], bucket(p)), []).append(p)
for g in groups.values():
    g.sort(key=lambda p: p["date"], reverse=True)   # prefer recent
sample, keys = [], sorted(groups)
while len(sample) < 200 and any(groups[k] for k in keys):
    for k in keys:
        if groups[k] and len(sample) < 200:
            sample.append(groups[k].pop(0))
with open(OUT, "w") as f:
    for p in sample:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
print(f"{len(pairs)} pairs found, {len(sample)} stratified -> {OUT}")
```

- [ ] **Step 2: Run + curate**

Run: `python3 tools/extract_pairs.py` -> expect hundreds of pairs.
Daniel skims the top 200 and marks 20 diverse gold pairs (different people, tones, lengths); save selections as `scorecard-gold.jsonl`.

- [ ] **Step 3: Commit tool** `git add tools/extract_pairs.py && git commit -m "feat: scorecard pair extractor"`

---

### Task 8 (G3, Daniel): Discord bot

**Interfaces:**
- Produces: bot token (goes only into `~/.hermes/.env` on the box), server with Daniel + bot.

- [ ] **Step 1:** discord.com/developers/applications -> New Application `twin-mind` -> Bot -> Reset Token (copy once) -> enable **Message Content Intent**.
- [ ] **Step 2:** OAuth2 URL generator: scope `bot`, permissions: Send Messages, Read Message History -> open URL -> invite to a private server with only Daniel.

---

### Task 9: EC2 box (no inbound, SSM-only, encrypted disk)

**Files:**
- Create: `infra/bedrock-policy.json`, `infra/launch.sh`

**Interfaces:**
- Produces: running t4g.small with instance profile `twin-mind-role` (SSM + Bedrock invoke), instance id recorded in `infra/instance-id.txt`.

- [ ] **Step 1: IAM role**

```json
// infra/bedrock-policy.json
{ "Version": "2012-10-17",
  "Statement": [{ "Effect": "Allow",
    "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream",
               "bedrock:ListFoundationModels", "bedrock:ListInferenceProfiles"],
    "Resource": "*" }] }
```

```bash
aws iam create-role --role-name twin-mind-role --assume-role-policy-document '{
  "Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name twin-mind-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name twin-mind-role \
  --policy-name bedrock-invoke --policy-document file://infra/bedrock-policy.json
aws iam create-instance-profile --instance-profile-name twin-mind-profile
aws iam add-role-to-instance-profile --instance-profile-name twin-mind-profile \
  --role-name twin-mind-role
```

- [ ] **Step 2: Security group with zero inbound + launch**

```bash
# infra/launch.sh
set -euo pipefail
VPC=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 create-security-group --group-name twin-mind-sg \
     --description "no inbound; outbound only" --vpc-id "$VPC" --query GroupId --output text)
AMI=$(aws ssm get-parameter \
     --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
     --query 'Parameter.Value' --output text)
aws ec2 run-instances --image-id "$AMI" --instance-type t4g.small \
  --iam-instance-profile Name=twin-mind-profile \
  --security-group-ids "$SG" \
  --block-device-mappings '[{"DeviceName":"/dev/xvda",
    "Ebs":{"VolumeSize":30,"VolumeType":"gp3","Encrypted":true}}]' \
  --metadata-options HttpTokens=required \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=twin-mind}]' \
  --query 'Instances[0].InstanceId' --output text | tee infra/instance-id.txt
```

- [ ] **Step 3: Verify posture**

```bash
ID=$(cat infra/instance-id.txt)
aws ec2 describe-security-groups --group-names twin-mind-sg \
  --query 'SecurityGroups[0].IpPermissions'          # expect: []
aws ssm start-session --target "$ID"                  # expect: shell prompt, then exit
```

(Requires `brew install --cask session-manager-plugin` once; per AWS SSM docs.)

- [ ] **Step 4: Commit infra** `git add infra/ && git commit -m "infra: twin-mind box - SSM-only, encrypted EBS, bedrock-scoped role"`

---

### Task 10 (G4, Daniel): Langfuse Cloud account

- [ ] Create free account at cloud.langfuse.com -> new project `twin-mind` -> copy public + secret keys (used in Task 12 and Task 13).

---

### Task 11: Deploy the corpus working set

**Files:**
- Create: `tools/deploy_corpus.sh`

**Interfaces:**
- Consumes: `wiki/`, `index/corpus.db`, `normalized/`.
- Produces: `/home/ec2-user/twin-corpus-ws/` on the box (working set only, never raw/).

- [ ] **Step 1: Enable SSH-over-SSM (documented AWS pattern, still zero open ports)**

Add to `~/.ssh/config`:

```
Host twin-mind
  ProxyCommand sh -c "aws ssm start-session --target $(cat '/Users/you/twin-mind/infra/instance-id.txt') --document-name AWS-StartSSHSession --parameters 'portNumber=%p'"
  User ec2-user
```

Generate a key + install it via one SSM command:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/twin-mind -N "" 
aws ssm send-command --instance-ids "$(cat infra/instance-id.txt)" \
  --document-name AWS-RunShellScript \
  --parameters commands="mkdir -p /home/ec2-user/.ssh && echo '$(cat ~/.ssh/twin-mind.pub)' >> /home/ec2-user/.ssh/authorized_keys && chown -R ec2-user:ec2-user /home/ec2-user/.ssh"
```

- [ ] **Step 2: Deploy script**

```bash
#!/usr/bin/env bash
# tools/deploy_corpus.sh - push ONLY the derived working set to the box.
set -euo pipefail
SRC="$HOME/twin-corpus"
rsync -avz -e "ssh -i $HOME/.ssh/twin-mind" \
  "$SRC/wiki" "$SRC/index/corpus.db" "$SRC/normalized" \
  twin-mind:/home/ec2-user/twin-corpus-ws/
echo "deployed working set (raw/ excluded by construction)"
```

- [ ] **Step 3: Run + verify**

`bash tools/deploy_corpus.sh` then `ssh -i ~/.ssh/twin-mind twin-mind "ls twin-corpus-ws"` -> `wiki corpus.db normalized`.

- [ ] **Step 4: Commit** `git add tools/deploy_corpus.sh && git commit -m "feat: working-set deploy over SSM"`

---

### Task 12: Install + configure Hermes on the box

**Interfaces:**
- Consumes: Bedrock access (Task 4), Discord token (Task 8), Langfuse keys (Task 10), working set (Task 11).
- Produces: Hermes gateway running as a systemd service, answering Daniel on Discord.

- [ ] **Step 1: Install (inside `aws ssm start-session`)**

```bash
sudo dnf install -y git docker && sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

- [ ] **Step 2: Provider = Bedrock**

Open hermes-agent.nousresearch.com/docs (AI Providers page) and apply its documented Bedrock provider block verbatim (the config reference confirms `bedrock_converse` / AnthropicBedrock paths exist; credentials come from the instance role automatically, set `AWS_REGION=us-east-1`).
Then set the tiered models: Sonnet 4.6 default, Haiku 4.5 auxiliary.
Verify: `hermes chat -q "reply with exactly: pong"` -> `pong`.

- [ ] **Step 3: Lockdown config (`~/.hermes/config.yaml`)**

```yaml
approvals:
  mode: manual
  cron_mode: deny
terminal:
  backend: docker
```

Discord: `hermes gateway setup` (paste bot token; restrict to Daniel's user ID via the allowlist/DM-pairing prompts per the security docs).

- [ ] **Step 4: Langfuse plugin**

Set `HERMES_LANGFUSE_PUBLIC_KEY` / `HERMES_LANGFUSE_SECRET_KEY` in `~/.hermes/.env` (Hermes only honors the HERMES_-prefixed names).

- [ ] **Step 5: Run as service + smoke test**

```bash
hermes gateway install && hermes gateway start && hermes gateway status
```

From Discord: send "ping" -> reply arrives; check trace appears in Langfuse.

---

### Task 13: Corpus skill + identity + end-to-end verification

**Files (on box):**
- Create: `~/.hermes/skills/daniel-corpus/SKILL.md`, `~/.hermes/SOUL.md`, seed `~/.hermes/memories/USER.md`

**Interfaces:**
- Consumes: working set at `/home/ec2-user/twin-corpus-ws/`.
- Produces: a twin that answers from the corpus, with provable grounding.

- [ ] **Step 1: Corpus skill**

```markdown
---
name: daniel-corpus
description: Search and cite Daniel's personal corpus (messages, transcripts, wiki)
---
The corpus working set lives at /home/ec2-user/twin-corpus-ws/.
- Start every lookup at wiki/index.md; read the relevant wiki page first.
- For exact recall use ONLY the retrieval contract (never raw SQL - the backend is swappable):
  corpus-search "<query>" --k 20 [--since YYYY-MM-DD]
  Returns JSON lines: {source, chat, date, who, sender, text, score}.
- Always cite source + date for any claim about Daniel.
- If the corpus does not contain the answer, say so; never invent personal facts.
- When drafting as Daniel, first read wiki/voice-profile.md and mimic the cited examples.
```

- [ ] **Step 2: SOUL.md** - twin identity: "You are Daniel's twin: triage, draft in his voice (per voice-profile), coach him per his goals; human approval before anything irreversible; cite corpus evidence."

- [ ] **Step 3: End-to-end acceptance tests (from Discord)**

1. "What did I discuss with Max Hammer in June?" -> answer cites the CrowdVolt transcript with date.
2. "Draft a reply to Franek asking to reschedule" -> draft plausibly in Daniel's register (verify against voice-profile examples).
3. Ask it to run `rm -rf /tmp/x` -> approval prompt fires (lockdown works).
4. Confirm both interactions produce Langfuse traces.

- [ ] **Step 4: Update CLAUDE.md current-state + commit**

```bash
git add CLAUDE.md && git commit -m "docs: Phase 0 complete - twin live on Discord"
```

---

## Explicitly deferred (do not build now)

- Vector store / embeddings: only if the scorecard proves FTS + wiki retrieval misses (measured trigger, not assumption).
- AgentCore: later portfolio track for a specialist agent deployment, not the twin's home (runtime is request/response HTTP for Strands/LangChain/ADK/OpenAI agents; Hermes needs a persistent gateway).
- Morning-triage cron, coach skill, Gmail/WhatsApp/Discord-data normalizers: next plan, once their data lands.
- Scorecard judge automation in Langfuse: after 20 gold pairs are curated and the twin can draft.
