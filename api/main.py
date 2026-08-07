from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from search import semantic_search
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="VectorVibe API")

# Allow the Next.js frontend to call this API
app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── GET /search ──────────────────────────────
@app.get("/search")
async def search(
    q: str = Query(..., description="Any search query"),
    gender: str | None = Query(None, enum=["m", "f", "unisex"]),
    price_max: float | None = None,
    limit: int = Query(100, le=200)
):
    results = semantic_search(q, limit=limit,
                              gender=gender, price_max=price_max)
    log_search(q, [r['id'] for r in results])
    return {"query": q, "count": len(results), "results": results}

# ── GET /suggest ─────────────────────────────
@app.get("/suggest")
async def suggest(q: str):
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT query FROM search_log
        WHERE query ILIKE %s
        ORDER BY query LIMIT 8
    """, (f"{q}%",))
    suggestions = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return {"suggestions": suggestions}

# ── POST /click ──────────────────────────────
class ClickEvent(BaseModel):
    query: str
    product_id: int

@app.post("/click")
async def log_click(event: ClickEvent):
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute("""
        UPDATE search_log SET clicked_id = %s
        WHERE query = %s AND clicked_id IS NULL
        ORDER BY created_at DESC LIMIT 1
    """, (event.product_id, event.query))
    conn.commit()
    cur.close()
    conn.close()
    return {"ok": True}

# ── GET /health ──────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "message": "VectorVibe API is running"}

def log_search(query: str, result_ids: list[int]):
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO search_log (query, result_ids) VALUES (%s, %s)",
            (query, result_ids)
        )
        conn.commit()
        cur.close()
        conn.close()
    except:
        pass