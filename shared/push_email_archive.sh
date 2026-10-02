#!/usr/bin/env bash
# Push email_archive.py to the box and run it. Run from the repo root.
#
#   bash shared/push_email_archive.sh              # dry run: counts, no writes
#   bash shared/push_email_archive.sh --execute    # label and archive
#   bash shared/push_email_archive.sh --restore    # undo
#
# The script it pushes never sets \Deleted and never expunges. It archives by
# removing the Inbox label through Google's X-GM-LABELS extension, so no Gmail
# setting can turn it into a deletion, and every message stays in All Mail.
set -euo pipefail

REGION=eu-west-1
INSTANCE=$(cat infra/instance-id.txt 2>/dev/null || true)
[ -n "$INSTANCE" ] || { echo "infra/instance-id.txt is missing; see README"; exit 1; }
SRC=shared/email_archive.py
DEST=/home/ec2-user/tools/email_archive.py

[ -f "$SRC" ] || { echo "run this from the repo root"; exit 1; }
BLOB=$(gzip -c "$SRC" | base64 | tr -d '\n')

CMDS=$(python3 - "$BLOB" "$DEST" "${1:-}" <<'PY'
import json, sys
blob, dest, extra = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({"commands": [
    f"echo '{blob}' | base64 -d | gunzip > {dest}",
    f"chown ec2-user:ec2-user {dest}",
    f"python3 -c 'import ast;ast.parse(open(\"{dest}\").read());print(\"parsed ok\")'",
    f"su - ec2-user -c 'python3 {dest} {extra} 2>&1'",
]}))
PY
)

ID=$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE" \
  --document-name AWS-RunShellScript --timeout-seconds 1800 \
  --parameters "$CMDS" --query 'Command.CommandId' --output text)

echo "command: $ID"
echo "waiting ..."
until [ "$(aws ssm get-command-invocation --region "$REGION" --command-id "$ID" \
      --instance-id "$INSTANCE" --query Status --output text 2>/dev/null)" != "InProgress" ]; do
  sleep 5
done
aws ssm get-command-invocation --region "$REGION" --command-id "$ID" \
  --instance-id "$INSTANCE" --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
