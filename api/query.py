"""api/query.py

The ONE place a raw user string becomes a vector.

Nothing else in the codebase should call the text encoder directly. Keeping a
single seam here is what lets us add caching, templating and expansion without
touching search.py again.

Layer 1  -- prompt templating           (on by default, ~free)
Layer 3  -- expansion cache lookup      (on by default, falls back safely)

Layer 2 (multi-template ensembling) deliberately does NOT run here. Five ONNX
passes on Railway's CPU would land on exactly the queries that are already
slowest. Ensembling happens offline in scripts/expand_queries.py, where there
is a GPU and nobody is waiting.
"""

import os
from typing import Callable, Sequence

from dotenv import load_dotenv

# Load .env HERE, not just in main.py. This module reads QUERY_TEMPLATE and
# QUERY_EXPANSION the moment it's imported (see below), which can happen
# before main.py's own load_dotenv() call runs, depending on import order.
# Without this, both silently fall back to their "on" defaults regardless
# of what .env actually says. Calling load_dotenv() twice is harmless.
load_dotenv()

from embed_text_onnx import cached_embed_text

# NOTE: no lru_cache here. embed_text_onnx.cached_embed_text is already
# keyed on the text handed to the encoder -- which, once we template below,
# IS the templated string. A second cache would just duplicate memory.

TEMPLATE = "{}, product photo"  # deliberately light -- the 7-word version
                                  # tested earlier overwhelmed short queries

# If a query already names a real garment, it's already anchored in
# product-photo space -- templating only dilutes it, which is exactly what
# broke "black slip dress" in the first Layer 1 test. Templating exists to
# help queries with NO garment noun at all ("titanic", "mechanic").
# TODO: this list is hand-written as a starting point. Worth cross-checking
# against `SELECT DISTINCT category FROM products` to catch anything the
# catalogue actually uses that isn't guessed here (e.g. "co-ord", "playsuit").
GARMENT_NOUNS = {
    "dress", "jacket", "skirt", "jumper", "sweater", "blazer", "coat",
    "trousers", "pants", "jeans", "shirt", "blouse", "shorts", "jumpsuit",
    "cardigan", "top", "gown", "suit", "boots", "shoes", "heels",
    "sneakers", "bag", "scarf", "hat", "playsuit", "romper", "leggings",
    "bodysuit", "kimono", "cape", "poncho", "vest", "tank",
}


def has_garment_noun(q: str) -> bool:
    return bool(set(q.lower().split()) & GARMENT_NOUNS)

# Env vars, not constants, so you can flip either on Railway without a
# redeploy. A/B testing becomes a 30-second operation.
USE_TEMPLATE = os.getenv("QUERY_TEMPLATE", "on").lower() == "on"
USE_EXPANSION = os.getenv("QUERY_EXPANSION", "on").lower() == "on"

# A lookup takes a normalised query and returns a stored 512-dim vector,
# or None if we've never expanded that query. search.py supplies it; keeping
# it injected means query.py owns no database connection of its own.
ExpansionLookup = Callable[[str], Sequence[float] | None]


def normalise(raw: str) -> str:
    """The single definition of query identity.

    Used for the lru_cache key, the expansion cache key, and the batch job's
    dedup. If this ever changes, the expansion cache must be rebuilt -- every
    stored key would be computed under the old rule.
    """
    return " ".join(raw.lower().split())


def _embed(text: str) -> tuple[float, ...]:
    """Thin pass-through. The real cache lives in embed_text_onnx."""
    return cached_embed_text(text)


def query_vector(raw: str, lookup: ExpansionLookup | None = None) -> list[float]:
    """Turn a user's raw query into a vector to search with.

    Warm path  -- expansion cache hit: returns a stored vector. No encoder
                  call at all, so this is FASTER than the current code.
    Cold path  -- single templated encoder pass. Same cost as today.

    The user never waits on an LLM in either case. Expansion is produced
    offline by the nightly batch job.
    """
    q = normalise(raw)

    if USE_EXPANSION and lookup is not None:
        try:
            cached = lookup(q)
            if cached is not None and len(cached) == 512:
                return list(cached)
        except Exception:
            # A broken cache must never break search. Fall through.
            pass

    text = q if not USE_TEMPLATE else (
        q if has_garment_noun(q) else TEMPLATE.format(q)
    )
    return list(_embed(text))