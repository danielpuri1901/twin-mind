"""The embedding contract. One place, because five writers had drifted apart.

Every path that puts a vector in the index must agree on exactly what text it
embeds, or the same record gets a different vector depending on how it
arrived. Measured on 2026-09-29, the writers did not agree:

    pipeline/embed_corpus.py         text[:1500]   full rebuild
    pipeline/ingest_twin_chat.py     text[:2048]   the 30-minute timer
    pipeline/ingest_wispr_meetings   text[:2048]
    infra/.../twin-episodic          text[:2048]
    pipeline/backfill/*              text[:2048]

2,808 of 8,366 vectors are over 1,500 characters, and 1,749 sit in the window
where the two caps actually differ. Traced one real 1,607-character transcript
through both: cosine distance 0.0055 and 1,021 of 1,024 dimensions changed.
Small, but in a KNN over 8,366 vectors near-neighbours are routinely closer
together than that, so results reorder depending on provenance rather than on
meaning.

2048 wins over 1500 because more of the record reaches the model and nothing
argues for throwing the tail away. That choice costs one full re-embed.

The model id belongs here for the same reason: it is written into
`vec_meta.model` on every insert, and a writer naming a different one would
poison the column that exists to detect exactly that.

IF YOU CHANGE MAX_CHARS OR MODEL, EVERY EXISTING VECTOR IS STALE. The embedded
string changes, so the whole index must be rebuilt. Adding records never
requires that; changing this file always does.

`evals/test_embedding_contract.py` greps every writer and fails if one drifts.
"""

MODEL = "cohere.embed-multilingual-v3"

# Cohere v3 output width. vec_idx is declared float[1024]; changing this means
# recreating the virtual table, not just re-embedding.
DIM = 1024

# Characters of a record that reach the model. Cohere also truncates on its own
# side (truncate="END"), but doing it here keeps the embedded string explicit
# and identical across writers.
MAX_CHARS = 2048

# Below this a record is an acknowledgement, not something to match on. It
# stays in FTS5, where a keyword search can still find it, and out of the
# vector index, where it would only add noise. This floor is what makes the
# FTS/vector parity check exact rather than approximate.
MIN_CHARS = 12

# Cohere v3 accepts at most 96 texts per call. The incremental writers use 90
# for headroom; a full build uses the maximum.
BATCH = 96
BATCH_INCREMENTAL = 90

# Asymmetric on purpose: Cohere v3 projects queries and documents differently.
# Swapping these does not error, it only ranks worse, permanently and silently.
INPUT_DOCUMENT = "search_document"
INPUT_QUERY = "search_query"


def embed_body(texts, input_type=INPUT_DOCUMENT, max_chars=MAX_CHARS):
    """The exact request body every writer should send."""
    import json
    return json.dumps({
        "texts": [(t or "")[:max_chars] for t in texts],
        "input_type": input_type,
        "truncate": "END",
    })


def worth_embedding(text) -> bool:
    return len((text or "").strip()) >= MIN_CHARS
