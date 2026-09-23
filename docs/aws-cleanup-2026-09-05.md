# AWS cleanup verification, 2026-09-05

This work implements the five account changes authorized in the Twin Mind cleanup conversation.
The account is `<account-id>` (kept in the private env, `TWIN_AWS_ACCOUNT_ID`), with `eu-west-1` as the home Region.
Run `python3 infra/check_aws.py` for the read-only configuration checks.
No secret values are retrieved by that script.

## Cost alerts and budgets

The existing anomaly subscription now sends daily alerts to Daniel's confirmed email address when absolute anomaly impact is at least $10.
The `project` cost allocation tag is active.
`twin-mind-monthly` and `agentlab-monthly-cost` each retain their $50 monthly limits and filter on `user:project$twin-mind` and `user:project$agentlab`, respectively.
The new `account-monthly` budget has a $50 monthly limit without a project filter, actual alerts at 80% and 100%, and a forecast alert at 100%.
All three budgets exclude credits and refunds so credits cannot hide compute spend.
The existing zero-spend budget is unchanged.
Budget creation templates are `infra/budget.json`, `infra/agentlab-budget.json`, and `infra/account-budget.json`.
The audit checks their filters and limits against the live budgets.

Application profiles are active and tagged:

| Name | Profile ID | Project | Source model |
| --- | --- | --- | --- |
| twin-mind-sonnet | r9bht745cst4 | twin-mind | eu.anthropic.claude-sonnet-4-6 |
| agentlab-sonnet | mfzwa25maf8z | agentlab | global.anthropic.claude-sonnet-4-6 |
| agentlab-haiku | kpbqsnaqf2ti | agentlab | global.anthropic.claude-haiku-4-5-20251001-v1:0 |

The Twin instance and its encrypted volume carry `project=twin-mind`.
Tagged budgets are attribution tools, not complete project invoices until all callers and billable resources are covered.
Cohere embeddings, the unchanged LangSmith judge key, legacy eval scripts that call bare model IDs, and other untagged services remain covered by the account-wide budget.
Billing data and tag attribution are delayed; no completed billing-period reconciliation is claimed here.

## CloudTrail and alarms

`twin-mind-account` is a multi-region trail with global service events and log-file validation enabled.
It delivers to `twin-mind-cloudtrail-<account-id>` and `/aws/cloudtrail/twin-mind-account`.
The bucket blocks public access, uses SSE-S3 encryption, and expires objects after 400 days.
CloudWatch Logs retention is 90 days.
Both S3 and CloudWatch delivery timestamps were verified, with no delivery errors.
The role policy and bucket policy previously contained malformed ARNs caused by shell variable expansion.
They now contain complete ARNs, and the role trust is restricted to this account and trail.

Four alarms cover root use, IAM policy/user/key creation changes, console login without MFA, and trail changes.
Every filter passed positive and negative synthetic tests through `test-metric-filter`.
The actual IAM cleanup triggered `twin-mind-security-IAMPolicyChanges` at 19:26:55 CEST.
CloudWatch recorded successful execution of its SNS action, and the alarm returned to OK.
The SNS email subscription is confirmed.
Email arrival was not checked in Daniel's inbox, and no fake root-login event was injected.

## Bedrock logs without payloads

The destination is `/aws/bedrock/model-invocations`, with 90-day retention.
Text, image, embedding, video, and audio delivery flags are all false.
No S3 destination for model bodies is configured.
A harmless synthetic Converse invocation produced a `ModelInvocationLog` record containing caller identity, model, operation, token counts, and cache counts, without request or response bodies.
Subsequent streaming and non-streaming probes under the Twin instance role produced the same payload-free schema.
This is observed behavior of the tested APIs and configuration, not a claim that the API documentation guarantees metadata-only behavior for every modality.
The audit checks sampled delivered records for body fields and S3 body references.
Text payload logging was never enabled during this work.

## Twin routing and caching

The deployed Hermes adapter recognizes Claude from its logical model ID and does not recognize an opaque application profile ARN as Claude.
Changing the configured model to the ARN would therefore select a different SDK path.
The `bedrock-profiles` plugin instead wraps the final `create_anthropic_message` call after provider detection and message construction.
It replaces only the SDK model argument for `AnthropicBedrock` clients.
The logical model, cache markers, context-limit lookup, and streaming preference are unchanged.
The shared structured-output helper and weekly recap route their Converse calls through the same Twin profile.

The plugin was discovered by the deployed Hermes plugin manager with `enabled=True` and no error.
A synthetic instance-role test wrote 3,610 cache tokens on its first streaming call.
Its repeated streaming call and subsequent non-streaming call each read 3,610 cached tokens.
A forced-tool-use call through `shared.structured` passed under the instance role.
The gateway was restarted after these checks and returned to active state.
The module-level adapter patch applies to the runtime import used by the main chat call path.

Before replacement, deployed existing files were checked against the repository's original SHA-256 hashes.
Backups use the `.before-aws-cleanup` suffix on the box, including its configuration.
To roll back routing, remove `bedrock-profiles` from the enabled plugin list, restore the structured helper and recap backups, and restart `hermes-gateway.service`.
Keep logging and account-wide budget coverage enabled during rollback.
Hermes upgrades require repeating plugin discovery, streaming, and cache verification because the plugin wraps an internal runtime function.

## Agentlab routing

Agentlab's `infra/ecs.tf` now sets `PROPOSER_MODEL`, `DEEP_READ_MODEL`, and `PICK_MODEL` to the tagged Haiku and Sonnet profiles.
The active definitions are `agentlab-proposer:4` and `agentlab-explain:4`.
All four existing schedules reference revision 4, with their schedule expressions and enabled states unchanged.
Synthetic ECS probes used the production images and task roles and exited with code 0 for both proposer and explain.
The delegated deployment reported all three LiteLLM profile calls succeeded and the full Terraform plan showed no changes.
The stopped probe tasks and their exit codes were independently checked through ECS.
No production video workload was started by this verification.
Unrelated Agentlab edits, including work arriving during this session, were preserved.

## IAM cleanup

The dormant `nathan-bedrock`, `daniel-iam`, and unused `BedrockAPIKey-150t` users were removed with their associated access methods and policy attachments.
Only `daniel-admin` and the live `BedrockAPIKey-edsw` judge user remain.
The LangSmith judge secret was neither retrieved nor printed nor rotated.
Its previously requested rotation remains Daniel's separate action.

## Tests

The final `sh evals/eval.sh` run completed after the recap and gate changes.
Both profile-routing tests passed, along with the existing deterministic tool, prep, watchdog, and ingestion suites.
The live triage regression passed all nine trials and printed `EVAL GATE: GREEN`.
The additional brief-content checks passed all 15 tests.
Python compilation and `git diff --check` passed.
The optional `--full` composition benchmark and judge-alignment suite were not run because no prompt, judge rubric, or model tier changed.

## Files changed

Twin Mind runtime and tests:

- `shared/bedrock_profiles.py`
- `shared/structured.py`
- `agents/weekly-recap/tools/recap.py`
- `infra/hermes-plugins/bedrock-profiles/__init__.py`
- `infra/hermes-plugins/bedrock-profiles/plugin.yaml`
- `infra/box-config.yaml`
- `evals/test_bedrock_profiles.py`
- `evals/eval.sh`

AWS configuration and verification:

- `infra/budget.json`
- `infra/account-budget.json`
- `infra/agentlab-budget.json`
- `infra/security-filters.json`
- `infra/check_aws.py`
- `docs/aws-cleanup-2026-09-05.md`

Agentlab: `infra/ecs.tf` only.
No changes were committed or pushed.

## Sources

- [CloudTrail permissions for CloudWatch Logs](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-required-policy-for-cloudwatch-logs.html)
- [CloudTrail delivery to CloudWatch Logs](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/send-cloudtrail-events-to-cloudwatch-logs.html)
- [Bedrock invocation logging](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html)
- [Bedrock LoggingConfig API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_LoggingConfig.html)
- [Bedrock application inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/cost-mgmt-application-inference-profiles.html)

`CHANGELOG.md` is intentionally untouched under the current global rule.
