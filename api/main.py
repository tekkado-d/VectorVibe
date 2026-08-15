import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager, contextmanager

import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from search import semantic_search
import query as query_mod
import search as search_mod

load_dotenv()

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
log = logging.getLogger("api")

DB_POOL: pool.SimpleConnectionPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global DB_POOL
    DB_POOL = pool.SimpleConnectionPool(1, 5, dsn=os.getenv("DATABASE_URL"))
    print("VectorVibe API starting — ONNX text encoder")
    yield
    if DB_POOL:
        DB_POOL.closeall()


app = FastAPI(title="VectorVibe API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── timing middleware ──────────────────────────────────────────────────────
# Registered AFTER CORS, so it wraps it and measures the full request.
# One minified JSON line per request: Railway drops logs above 500 lines/sec,
# and minified JSON stays greppable and parseable later.
@app.middleware("http")
async def timing(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    log.info(
        json.dumps(
            {
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - t0) * 1000),
            },
            separators=(",", ":"),
        )
    )
    return response


# ── connection helper ──────────────────────────────────────────────────────
# Borrows from the pool and ALWAYS returns it, even on exception.
@contextmanager
def db():
    conn = DB_POOL.getconn()
    try:
        yield conn
    finally:
        DB_POOL.putconn(conn)


@app.get("/health")
async def health():
    return {"status": "ok", "message": "VectorVibe API is running"}


@app.get("/config")
async def config():
    """Lets the baseline harness record what settings produced a snapshot."""
    return {
        "probes": search_mod.PROBES,
        "template": query_mod.USE_TEMPLATE,
        "expansion": query_mod.USE_EXPANSION,
        "template_text": query_mod.TEMPLATE,
    }


# ── GET /search ────────────────────────────────────────────────────────────
# Plain `def`, NOT `async def`. semantic_search blocks on the database, and
# blocking inside async def freezes the event loop for every other request.
# With sync def, FastAPI runs this in a threadpool where blocking is safe.
@app.get("/search")
def search(
    background: BackgroundTasks,
    q: str = Query(..., description="Any search query"),
    gender: str | None = Query(None),
    price_min: float | None = None,
    price_max: float | None = None,
    category: str | None = None,
    brand: str | None = None,
    limit: int = Query(100, le=200),
):
    stats: dict = {}
    t0 = time.perf_counter()
    results = semantic_search(
        q,
        limit=limit,
        gender=gender,
        price_min=price_min,
        price_max=price_max,
        category=category,
        brand=brand,
        stats=stats,
    )
    ms_total = round((time.perf_counter() - t0) * 1000)

    # Queued, not awaited: runs AFTER the response is sent, so the user
    # never waits on the log write.
    background.add_task(log_search, q, [r["id"] for r in results], ms_total, stats)

    return {"query": q, "count": len(results), "results": results}


@app.get("/suggest")
def suggest(q: str):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT query FROM search_log
                WHERE query ILIKE %s
                ORDER BY query LIMIT 8
                """,
                (f"{q}%",),
            )
            suggestions = [row[0] for row in cur.fetchall()]
    return {"suggestions": suggestions}


class ClickEvent(BaseModel):
    query: str
    product_id: int


@app.post("/click")
def log_click(event: ClickEvent):
    # PostgreSQL does NOT support UPDATE ... ORDER BY ... LIMIT (that's MySQL).
    # The old version threw on every call, so no click has ever been recorded.
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE search_log SET clicked_id = %s
                    WHERE id = (
                        SELECT id FROM search_log
                        WHERE query = %s AND clicked_id IS NULL
                        ORDER BY created_at DESC LIMIT 1
                    )
                    """,
                    (event.product_id, event.query),
                )
                conn.commit()
                updated = cur.rowcount
        return {"ok": True, "updated": updated}
    except psycopg2.Error as e:
        log.warning(json.dumps({"event": "click_failed", "error": str(e)[:200]}))
        return {"ok": False}

class FeedbackEvent(BaseModel):
    query: str
    rating: int  # 1 = good, -1 = bad
 
 
@app.post("/feedback")
def log_feedback(event: FeedbackEvent):
    # Reject anything that isn't 1 or -1 rather than writing junk to the
    # column. This endpoint is public, so it will eventually be poked at.
    if event.rating not in (1, -1):
        return {"ok": False, "error": "rating must be 1 or -1"}
 
    # Same shape as /click: attach the rating to the most recent unrated
    # log row for this query. Postgres cannot do UPDATE ... LIMIT directly,
    # hence the subquery picking a single id.
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE search_log SET rating = %s
                    WHERE id = (
                        SELECT id FROM search_log
                        WHERE query = %s AND rating IS NULL
                        ORDER BY created_at DESC LIMIT 1
                    )
                    """,
                    (event.rating, event.query),
                )
                conn.commit()
                updated = cur.rowcount
        return {"ok": True, "updated": updated}
    except psycopg2.Error as e:
        log.warning(json.dumps({"event": "feedback_failed", "error": str(e)[:200]}))
        return {"ok": False}
    
def log_search(
    query: str,
    result_ids: list[int],
    ms_total: int | None = None,
    stats: dict | None = None,
):
    """Runs in the background after the response is sent."""
    s = stats or {}
    try:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO search_log
                        (query, result_ids, ms_embed, ms_search, ms_total,
                         cache_hit, n_results)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        query,
                        result_ids,
                        s.get("ms_embed"),
                        s.get("ms_search"),
                        ms_total,
                        s.get("cache_hit"),
                        s.get("n_results", len(result_ids)),
                    ),
                )
                conn.commit()
    except Exception as e:
        # Never let logging break a search -- but say something, so a
        # silently broken log table doesn't go unnoticed for weeks.
        log.warning(json.dumps({"event": "log_search_failed", "error": str(e)[:200]}))