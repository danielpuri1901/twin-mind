# Ingestion plan - collect everything

Goal: pull every piece of your data and online presence into one place, organized, so the twin can learn from it.

Rule of thumb: **raw files go in `raw/`, untouched. The LLM compiles them into the wiki later. You rarely touch the wiki by hand.** (Karpathy pattern.)

## Where it all lives

The corpus is the most sensitive data about you that will ever exist in one place. Treat it that way.

- Keep it **local and encrypted** (an encrypted volume or FileVault). Never push it to a public repo.
- Big media (photos, video) stays **outside git** - git is terrible with 120 GB of binaries. We index it, not copy it.

```
twin-corpus/
  raw/                 # everything you collect, untouched
    comms/             # email, X, social, messaging
    google/            # Google Takeout
    ai/                # Claude, ChatGPT, coding sessions
    code/              # repos + diffs
    health/            # Apple Health, wearables, medical
    finance/           # banks, cards, crypto, marketplaces, tax
    legal-identity/    # legal docs, public records, IDs
    education-career/   # transcripts, CVs, certs
    notes/             # Notion, Apple Notes, Granola, journals
    media/             # photo + video METADATA only (library stays elsewhere)
    web-footprint/     # browser history, public presence, archives
  wiki/                # LLM-compiled markdown (the brain). Viewable in Obsidian.
  index/               # cheap structured indexes (photo EXIF, finance CSVs)
```

## The full source list

✅ = you said you've done this (re-export fresh if it's old). ☐ = to do.

### Communications and social
- ✅ X / Twitter archive (Settings -> Download an archive)
- ☐ Instagram, Facebook (Meta -> Download Your Information)
- ☐ LinkedIn (Settings -> Get a copy of your data)
- ☐ Reddit (Settings -> Request data)
- ☐ Discord (Settings -> Data & Privacy -> Request all data)
- ☐ WhatsApp (per-chat export), Telegram (Desktop -> Export data), Signal
- ☐ TikTok, Snapchat (if used)
- ☐ iMessage + SMS (Mac: `~/Library/Messages/chat.db`, or a backup export)

### Google (one Takeout, select everything)
- ✅ Gmail, Calendar, Drive, Maps Timeline (location history), YouTube history, Chrome, search history
- ☐ Also grab in the same Takeout: Contacts, Keep, Tasks, Fit, Google Pay/transactions, Voice

### AI and code
- ✅ Claude export, ChatGPT export
- ✅ Coding sessions: Cursor, Claude Code, Codex, Droid, OpenCode
- ☐ Add if used: Gemini, Perplexity, Copilot, Aider, Windsurf
- ✅ Local code + diffs, GitHub repos
- ☐ GitHub account data export (Settings -> Export account data) - gets issues, PRs, gists, history in one bundle
- ☐ GitLab / Bitbucket if any

### Health and body
- ✅ Apple Health export (Health app -> profile -> Export All Health Data)
- ☐ Wearables: Whoop, Oura, Fitbit, Garmin, Strava
- ☐ Medical: patient portals (MyChart etc.), genetic data (23andMe / Ancestry)

### Finance and commerce (this answers "how much did I spend on X")
- ☐ Bank statements - export CSV/PDF for every account, all years
- ☐ Credit cards - transaction export
- ☐ PayPal, Venmo, Cash App, Wise, Revolut
- ☐ Crypto + brokerage - transactions and tax docs (exchanges, wallets)
- ☐ Marketplaces - eBay, TCGplayer, StockX (the trading-card spend lives here + in card-shop emails)
- ☐ Tax returns - every year
- ☐ Routes AI / business invoices and receipts
- ☐ Subscriptions list

### Legal and identity
- ✅ Photos of every legal document
- ✅ Public records of yourself
- ☐ Confirm coverage: passports, IDs, visas, immigration/citizenship docs, leases, contracts, diplomas, certifications

### Education and career
- ☐ Transcripts, diplomas, course materials, Canvas exports
- ☐ Every CV / resume / cover letter / portfolio version
- ☐ LinkedIn export (also above)

### Notes and personal knowledge
- ☐ Notion (Export -> Markdown & CSV)
- ☐ Apple Notes, Google Keep, Evernote/Obsidian/Roam/Logseq if used
- ☐ Granola meeting notes, voice memos
- ☐ Any journals or diaries
- ☐ Bookmarks: browser, Pocket, Raindrop
- ☐ Reading: Kindle highlights (Readwise), Goodreads, Spotify/Apple Music data export

### Web footprint and online presence
- ☐ Browser history, bookmarks, autofill (per browser)
- ☐ Domains you own (whois, site contents)
- ☐ Wayback Machine snapshots of your sites
- ☐ A discovery pass: search engines, GitHub, Google Scholar, your public profiles (LinkedIn, X, GitHub, Routes AI, personal site, blog posts, VS Code Marketplace, Gurobi GitHub/PyPI), any press mentions. I can run this for you with Exa and hand you a list to verify.

## The 120 GB of photos (do NOT brute-force this)

Captioning 120 GB of photos with a vision model would be slow and expensive, and you do not need it to answer most questions. Two cheap, high-value moves instead:

1. **Metadata index (nearly free, huge value).** Pull EXIF from every photo - date, GPS, device, filename - into one index file. This alone answers "where was I in March 2022," "what city, what month." Tools: `exiftool`, or for Apple Photos `osxphotos` (exports albums, faces, places, memories as data without touching pixels).
2. **Selective captioning (on demand).** Run a vision model only over curated albums, or only when a query needs it. Not all 120 GB upfront.

The library stays where it is (or on an encrypted external drive). The corpus only holds the **metadata index** plus captions for the photos that matter. The wiki references photos by path.

I will propose the exact `exiftool` / `osxphotos` commands and get your OK before installing or running anything.

## Start here (do not wait for all 120 GB)

You do not need everything collected before we build. Pull the high-value slice first - it is what the doer and coach need to sound like you and know you:

1. Email (sent + received) and messaging - for your voice
2. Your writing: notes, docs, posts, CVs
3. Calendar + contacts - context
4. AI coding sessions + code - for "what mistakes do I make"
5. Finance CSVs - for "how much did I spend"
6. Apple Health export - for "how many km"
7. Photo metadata index - for "where was I"

Everything else (full media, deep archives) keeps flowing in afterward. The wiki is built to grow.
