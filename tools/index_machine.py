#!/usr/bin/env python3
"""
index_machine.py - build a complete manifest of every file under HOME so the
corpus knows what exists. Pure metadata only: path, type, size, date. It reads
NO file contents and sends nothing anywhere. Writes one JSONL manifest to
~/twin-corpus/index/. Skips junk (caches, node_modules, git, app bundles, the
photo library, the corpus itself). Stdlib only.
"""
import os
import sys
import json
import time

HOME = os.path.expanduser("~")
OUT = os.path.join(HOME, "twin-corpus", "index", "file-manifest.jsonl")

# Directories we never descend into.
SKIP_DIRS = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", ".cache",
    "Library", ".Trash", "twin-corpus", ".npm", ".cargo", ".rustup",
    "go", ".gradle", "DerivedData", ".next", "dist", "build", ".terraform",
}
# Bundles treated as opaque (don't walk inside them).
SKIP_SUFFIX = (".app", ".photoslibrary", ".framework", ".bundle")

# Document types worth ingesting later. Flagged here, not read here.
DOC_EXTS = {
    "pdf", "doc", "docx", "pages", "txt", "md", "rtf", "csv",
    "xlsx", "xls", "ppt", "pptx", "key", "numbers", "epub", "html", "htm",
}


def main():
    counts, total = {}, 0
    # errors="backslashreplace" so one odd filename can't abort the whole run.
    with open(OUT, "w", errors="backslashreplace") as out:
        for root, dirs, files in os.walk(HOME):
            dirs[:] = [d for d in dirs
                       if d not in SKIP_DIRS and not d.endswith(SKIP_SUFFIX)]
            for name in files:
                path = os.path.join(root, name)
                if os.path.islink(path):
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                out.write(json.dumps({
                    "path": path,
                    "ext": ext,
                    "bytes": st.st_size,
                    "mtime": time.strftime("%Y-%m-%d", time.localtime(st.st_mtime)),
                    "doc": ext in DOC_EXTS,
                }) + "\n")
                total += 1
                counts[ext] = counts.get(ext, 0) + 1

    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:20]
    sys.stderr.write(f"indexed {total} files -> {OUT}\n")
    for ext, n in top:
        sys.stderr.write(f"  {n:>7}  .{ext or '(none)'}\n")


if __name__ == "__main__":
    main()
