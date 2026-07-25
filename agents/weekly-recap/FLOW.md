# Weekly recap - how a normal Friday runs

The intended weekly flow (built + live-tested 2026-07-18, "done"-gate design).
Three tools, all deterministic except the one compose call: `tools/nudge.py`, `tools/send_recap.py`, `tools/recap.py`.

```mermaid
sequenceDiagram
    autonumber
    participant CRON as Friday cron (box)
    participant NUDGE as nudge.py
    participant TG as Telegram
    participant D as Daniel
    participant POLL as send_recap.py<br/>(poll every ~2 min)
    participant DB as state.db
    participant COMPOSE as recap.py (Sonnet, temp 0)
    participant MAIL as Gmail (send-only)

    Note over CRON: Friday 18:00 (Europe/Luxembourg)
    CRON->>NUDGE: run
    NUDGE->>NUDGE: week_headlines()<br/>(CHANGELOG, deterministic - no LLM)
    NUDGE->>TG: "Your week - ..." + reflection prompt<br/>"reply freely, type 'done' when finished"
    NUDGE->>NUDGE: write nudge_ts, clear last week's sent-marker

    D->>TG: reflection messages<br/>(as many as he wants, no time pressure)
    TG->>DB: messages stored (role=user, timestamped)

    loop every ~2 min, 18:00-19:30
        POLL->>DB: messages since nudge_ts
        alt no "done" yet
            POLL-->>POLL: NOT ready - exit quietly<br/>(no LLM call, no cost)
        else Daniel says "done" (or a short "i'm done" variant)
            POLL->>DB: take everything BEFORE the done-signal = reflection
            POLL->>COMPOSE: compose(changelog_week, reflection)
            COMPOSE->>COMPOSE: 3 sections + WHO YOU MET<br/>grounding rule: only teach from quoted lines
            COMPOSE-->>POLL: recap text
            POLL->>MAIL: send "Weekly recap - week of ..." (recipient-locked)
            POLL->>POLL: write sent-marker (year-week)<br/>-> every later poll no-ops (idempotent)
        end
    end

    Note over POLL: safety net: if no "done" by +90 min,<br/>send with whatever was written (a forgotten<br/>thread still reaches the inbox)
```

## The three guards that make it safe

| Guard | Mechanism | Why |
|---|---|---|
| Human-in-the-loop gate | waits for a literal "done" from Daniel | the 07-18 live test fired mid-thread on a fixed timer and cut his reflection off |
| Idempotency | sent-marker `%Y-W%V`; polls no-op after one send | a 2-min poll can never double-send |
| Cutoff fallback | 90 min after nudge, send what exists | forgetting "done" degrades to the old behavior, not silence |

## Status - WIRED 2026-07-24 (first automatic run: tonight)

- Agent code: built, deployed on the box, live-tested end-to-end 2026-07-18 (gate held 10 min, sent once, then no-oped).
- Cron wired 2026-07-24, ship gate green: `weekly-recap-nudge.timer` (Fri 18:00 CEST) + `weekly-recap-poll.timer` (Fri 18:03-19:59, every 2 min).
- Race fixed at wiring time: the poll starts at 18:03 (after the nudge writes `nudge_ts`), AND `send_recap.py` refuses any `nudge_ts` older than 12h - so a poll can never compose off a previous week's nudge and fire early.
```
