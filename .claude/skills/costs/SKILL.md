---
name: costs
description: Answer "where is my money going" for Twin Mind - run evals/costs.py and interpret
---
Run: `python3 "evals/costs.py" --days 7` from the project root.

Then answer in Daniel's shape: 2-4 plain sentences, no dashboard talk.
- Lead with the total and the trend (rising/falling vs prior days).
- Name the driver in product terms (his chat session, briefs, experiments - infer from the day pattern and what happened those days).
- Only flag: a day > $5, a rising trend, or AWS services besides Bedrock/EBS appearing.
- If the AWS half says session expired, give the Langfuse half and note the CLI needs `aws login` for the service split - do not block on it.
Ground truth: EC2 free until Dec 2026; credits absorb everything (wallet $0); Sonnet 4.6 EU token rates are encoded in the script - do not re-derive from memory.
