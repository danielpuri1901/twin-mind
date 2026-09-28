"""Drop machine mail from the corpus. Keep everything Daniel wrote.

Measured 2026-09-28: 60% of the 5,421 gmail records come from noreply-style
senders. The single largest is no-reply@twitch.tv with 851, and Twitch plus
Steam together outnumber every message Daniel has ever sent (1,105). That
noise is not inert: semantic search for "keeping my private files in cloud
storage" returned four iCloud billing emails instead of the actual decision.

Rules, deliberately conservative:
  - never touch who='me'. His own writing is the most valuable thing here,
    it is how the drafting skills learn his voice.
  - only drop 'them' records whose sender matches a machine-mail pattern.
  - write every dropped row to a restore file first.

Reversible three ways: the restore file, the raw Takeout export on the Mac,
and the S3 copy.
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime

CORPUS = os.environ.get("TWIN_CORPUS_DIR") or os.path.expanduser("~/twin-corpus")
FTS_DB = os.path.join(CORPUS, "index", "corpus.db")
VEC_DB = os.path.join(CORPUS, "index", "vectors.db")
RESTORE = os.path.join(CORPUS, "normalized",
                       "gmail-noise-removed-%s.jsonl" % datetime.now().strftime("%Y%m%d"))

NOISE = re.compile(
    r"no-?reply|do-?not-?reply|notifications?@|updates?@|newsletter|marketing@|"
    r"mailer-daemon|mailer@|alerts?@|billing@|receipts?@|noreply|"
    r"@twitch\.tv|@steampowered\.com|@redditmail\.com|@supercell\.com|"
    r"@email\.apple\.com|@sona-systems\.net|@convertkit|@substack\.com",
    re.I)


def sender_of(chat):
    """Records carry '[sender · date]' in chat; take the sender half."""
    return str(chat or "").lstrip("[").split(" · ")[0].strip()


def main():
    dry = "--dry-run" in sys.argv
    fts = sqlite3.connect(FTS_DB, timeout=60)
    rows = fts.execute(
        "SELECT rowid, source, chat, date, who, sender, text FROM msgs WHERE source='gmail'"
    ).fetchall()

    doomed = [r for r in rows if r[4] != "me" and NOISE.search(sender_of(r[2]))]
    print(f"gmail records      : {len(rows)}")
    print(f"protected (who=me) : {sum(1 for r in rows if r[4] == 'me')}")
    print(f"to remove          : {len(doomed)}")
    print(f"kept               : {len(rows) - len(doomed)}")
    if dry:
        import collections
        for s, n in collections.Counter(sender_of(r[2]) for r in doomed).most_common(8):
            print("   %-46s %s" % (s[:46], n))
        return 0
    if not doomed:
        return 0

    with open(RESTORE, "w", encoding="utf-8") as fh:
        for r in doomed:
            fh.write(json.dumps({"source": r[1], "chat": r[2], "date": r[3],
                                 "who": r[4], "sender": r[5], "text": r[6]},
                                ensure_ascii=False) + "\n")
    print(f"restore file       : {RESTORE}")

    texts = {r[6] for r in doomed}
    fts.executemany("DELETE FROM msgs WHERE rowid=?", [(r[0],) for r in doomed])
    fts.commit()

    import sqlite_vec
    v = sqlite3.connect(VEC_DB, timeout=60)
    v.enable_load_extension(True); sqlite_vec.load(v); v.enable_load_extension(False)
    vids = [r[0] for r in v.execute("SELECT rowid, text FROM vec_meta WHERE source='gmail'")
            if r[1] in texts]
    for rid in vids:
        v.execute("DELETE FROM vec_idx WHERE rowid=?", (rid,))
        v.execute("DELETE FROM vec_meta WHERE rowid=?", (rid,))
    v.commit(); v.close()
    print(f"removed            : {len(doomed)} records, {len(vids)} vectors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
