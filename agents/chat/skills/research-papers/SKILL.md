---
name: research-papers
description: Find and summarize academic papers via the Semantic Scholar API (free, keyless)
---
When Daniel asks about research papers, use the Semantic Scholar Graph API via terminal curl. No key needed (rate-limited; be polite - one request per query, cache what you learn to wiki/learning/).

Search papers:
  curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query=<urlencoded>&limit=5&fields=title,year,abstract,citationCount,url,authors"

Paper details / citations (id from search):
  curl -s "https://api.semanticscholar.org/graph/v1/paper/<paperId>?fields=title,abstract,tldr,citationCount,references.title,citations.title"

Rules:
- Report title, year, citation count, and the tldr/abstract - never invent findings beyond what the abstract states.
- Distinguish clearly: "the abstract claims X" vs established consensus.
- If Daniel wants depth, offer to fetch the paper's references/citations to map the field.
- File anything Daniel wants to keep into wiki/learning/<topic>.md with the paper's URL and date.
