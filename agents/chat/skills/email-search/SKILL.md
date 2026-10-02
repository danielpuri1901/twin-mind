---
name: email-search
description: Search Daniel's Gmail live, read-only, for current mail. Use for anything the corpus cannot know yet.
---
Daniel's email is NOT in the corpus, by design. The corpus keeps what should surface without being asked; mail is what he asks about, so it is fetched live and stays current.

The one exception: his own sent mail IS in the corpus, as voice exemplars for drafting. Use `corpus-search --who me` for "how does Daniel write to X", and this tool for "what is in my mail".

    email-search "<text>" [--from <person>] [--days 90] [--limit 10] [--unread] [--sent] [--all-mail]

Returns JSON lines: {date, from, to, subject, folder, snippet}.

When to use it:
- Anything about current or recent mail: "did Juan reply", "what is unread", "find the invoice".
- Anything after 2026-07-02, which is where the corpus's mail snapshot ends.
- Checking a fact about a thread before answering, instead of guessing from the corpus snapshot.

When NOT to use it:
- "How does Daniel phrase things" -> `corpus-search --who me`.
- Anything about meetings or his own conversations -> `corpus-search`.
- Bulk reading. It fetches a page at a time on purpose; narrow with --from and --days rather than raising --limit.

Rules:
- It is READ-ONLY and must stay that way. Every mailbox is opened with readonly, and messages are fetched with BODY.PEEK so nothing is ever marked seen. Never add a send, delete or flag path to this tool; the morning brief sends mail through its own SMTP path.
- Always cite sender and date for any claim taken from mail.
- Mail is noisy. Roughly 60% of Daniel's inbox is machine mail, so say plainly when a search returns only notifications rather than dressing it up as an answer.
- Quote what the mail says. Do not infer a decision that the text does not state.
