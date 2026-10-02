#!/usr/bin/env bash
# Push the patched email_unsubscribe.py to the box and retry the three senders
# that failed on 2026-09-28. Run from the repo root.
#
#   bash shared/push_unsubscribe_fix.sh          # upload + report only
#   bash shared/push_unsubscribe_fix.sh --execute  # upload + retry the POSTs
#
# The patch fixes one failure: RFC 5322 folds a long List-Unsubscribe URL
# across lines, and the continuation whitespace ended up inside the URL, so
# urllib refused it. The other two failures were HTTP 403 from the senders
# themselves and no code change will clear those.
set -euo pipefail

REGION=eu-west-1
INSTANCE=$(cat infra/instance-id.txt 2>/dev/null || true)
[ -n "$INSTANCE" ] || { echo "infra/instance-id.txt is missing; see README"; exit 1; }
SRC=shared/email_unsubscribe.py
DEST=/home/ec2-user/tools/email_unsubscribe.py

[ -f "$SRC" ] || { echo "run this from the repo root"; exit 1; }
BLOB=$(gzip -c "$SRC" | base64 | tr -d '\n')

EXTRA=""
[ "${1:-}" = "--execute" ] && EXTRA=" --execute"

CMDS=$(python3 - "$BLOB" "$DEST" "$EXTRA" <<'PY'
import json, sys
blob, dest, extra = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({"commands": [
    f"echo '{blob}' | base64 -d | gunzip > {dest}",
    f"chown ec2-user:ec2-user {dest}",
    f"python3 -c 'import ast;ast.parse(open(\"{dest}\").read());print(\"parsed ok\")'",
    f"su - ec2-user -c 'python3 {dest} --top 45 --min-total 15{extra} 2>&1'",
]}))
PY
)

ID=$(aws ssm send-command --region "$REGION" --instance-ids "$INSTANCE" \
  --document-name AWS-RunShellScript --timeout-seconds 900 \
  --parameters "$CMDS" --query 'Command.CommandId' --output text)

echo "command: $ID"
echo "waiting ..."
until [ "$(aws ssm get-command-invocation --region "$REGION" --command-id "$ID" \
      --instance-id "$INSTANCE" --query Status --output text 2>/dev/null)" != "InProgress" ]; do
  sleep 5
done
aws ssm get-command-invocation --region "$REGION" --command-id "$ID" \
  --instance-id "$INSTANCE" --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
