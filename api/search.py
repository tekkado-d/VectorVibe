"""api/search.py -- pgvector similarity search."""

import json
import os
import time
from contextlib import contextmanager

import psycopg2
from dotenv import load_dotenv
from psycopg2 import pool

from query import normalise, query_vector

load_dotenv()

# -- the single biggest quality lever in this file -----------------------------
# pgvector defaults ivfflat.probes to 1, meaning each search examines only ONE
# of the index's clusters. Raise it and recall goes up at the cost of speed.
# sqrt(lists) is the starting point, not the answer -- validate empirically.
# With lists=285 that suggests ~17. Watch ms_search as you raise it.
PROBES = int(os.getenv("IVFFLAT_PROBES", "17"))

# -- which model's vectors to search -------------------------------------------
# MUST match the model_tag written by embed_products.py, and MUST match the
# model the ONNX text encoder was exported from. A mismatch does NOT error --
# it returns plausible-looking cosine scores from two incompatible vector
# spaces, i.e. silently broken search. This is the most dangerous single value
# in the codebase; change it only after encoder_check.py passes.
MODEL_TAG = f"{os.getenv('CLIP_MODEL', 'ViT-B-16')}/{os.getenv('CLIP_PRETRAINED', 'laion2b_s34b_b88k')}"

_pool: pool.SimpleConnectionPool | None = None


def _get_pool() -> pool.SimpleConnectionPool:
    """Lazy singleton. One pool per process, opened on first use."""
    global _pool
    if _pool is None:
        _pool = pool.SimpleConnectionPool(
            1, 10, dsn=os.getenv("DATABASE_URL"), connect_timeout=10
        )
    return _pool


@contextmanager
def _conn():
    """Borrow a connection and ALWAYS return it, even on exception.

    The old code called psycopg2.connect() per request with no finally: a fresh
    TCP + auth round trip every search (~3000ms), and a leaked connection on
    any error.
    """
    p = _get_pool()
    c = p.getconn()
    try:
        yield c
    finally:
        try:
            c.rollback()
        except Exception:
            pass
        p.putconn(c)


# -- Layer 3: expansion cache lookup -------------------------------------------
def expansion_lookup(q: str) -> list[float] | None:
    """Return the pre-computed vector for a query, or None if not expanded.

    A plain primary-key lookup -- no vector maths, no model call. That is why a
    cache hit is FASTER than the normal path, not slower.

    NOTE: cached vectors are model-specific. After a model change the whole
    query_expansions table must be re-embedded, or cache hits will serve
    vectors from the old space. expand_queries.py should stamp model_tag too.
    """
    try:
        with _conn() as c:
            with c.cursor() as cur:
                cur.execute(
                    """
                    SELECT embedding FROM query_expansions
                     WHERE query = %s
                       AND failed IS NOT TRUE
                       AND embedding IS NOT NULL
                    """,
                    (q,),
                )
                row = cur.fetchone()
        if not row or row[0] is None:
            return None
        # pgvector returns the column as text like '[0.1,-0.2,...]', which is
        # valid JSON, so json.loads parses it directly.
        return json.loads(row[0]) if isinstance(row[0], str) else list(row[0])
    except Exception:
        # A broken cache must never break search.
        return None


def semantic_search(
    query: str,
    limit: int = 100,
    gender: str | None = None,
    price_max: float | None = None,
    price_min: float | None = None,
    category: str | None = None,
    brand: str | None = None,
    stats: dict | None = None,
) -> list[dict]:
    """Find products matching a free-text query.

    stats: optional dict, filled in place with stage timings so main.py can
    write them to search_log without changing this function's return type.
    """
    t0 = time.perf_counter()
    norm = normalise(query)
    query_vec = query_vector(query, lookup=expansion_lookup)
    ms_embed = round((time.perf_counter() - t0) * 1000)

    # e.model_tag is the important addition: with two model configs coexisting
    # in the table during a migration, omitting it would mix vector spaces.
    filters = ["p.in_stock = TRUE", "p.active = TRUE", "e.model_tag = %s"]
    params: list = [str(query_vec), MODEL_TAG]

    # p.gender is unreliable: MERCHANT_GENDER maps one merchant to one gender,
    # which is wrong for merchants selling both. Do not wire this to the UI
    # until it is backfilled from a real per-row signal.
    if gender and gender != "all":
        filters.append("p.gender = %s")
        params.append(gender)

    # `is not None`, not truthiness -- price_min=0 is a legitimate filter that
    # `if price_min:` silently discarded.
    if price_min is not None:
        filters.append("p.price::numeric >= %s")
        params.append(price_min)
    if price_max is not None:
        filters.append("p.price::numeric <= %s")
        params.append(price_max)
    if category:
        filters.append("p.category ILIKE %s")
        params.append(f"%{category}%")
    if brand:
        filters.append("p.brand = %s")
        params.append(brand)

    where = " AND ".join(filters)
    params.append(str(query_vec))
    params.append(limit)

    # COALESCE on the image: prefer the merchant's hi-res original for display,
    # fall back to Awin's proxy where it is missing.
    sql = f"""
        SELECT
            p.id, p.name, p.brand, p.price,
            COALESCE(p.image_url_hires, p.image_url) AS image_url,
            p.affiliate_url, p.category, p.gender,
            1 - (e.embedding <=> %s::vector) AS similarity
        FROM product_embeddings e
        JOIN products p ON p.id = e.product_id
        WHERE {where}
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
    """

    t1 = time.perf_counter()
    with _conn() as c:
        with c.cursor() as cur:
            # SET LOCAL only applies inside a transaction and resets when it
            # ends, so it cannot leak to other queries on this pooled
            # connection. psycopg2 opens a transaction implicitly.
            cur.execute("SET LOCAL ivfflat.probes = %s", (PROBES,))
            cur.execute(sql, params)
            rows = cur.fetchall()
    ms_search = round((time.perf_counter() - t1) * 1000)

    cols = [
        "id", "name", "brand", "price", "image_url",
        "affiliate_url", "category", "gender", "similarity",
    ]
    results = [dict(zip(cols, row)) for row in rows]

    if stats is not None:
        stats.update({
            "ms_embed": ms_embed,
            "ms_search": ms_search,
            "n_results": len(results),
            # ms_embed under ~5ms means the expansion cache served this one.
            "cache_hit": ms_embed < 5,
            "normalised": norm,
            "model_tag": MODEL_TAG,
        })

    return results