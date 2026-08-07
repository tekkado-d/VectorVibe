import psycopg2
import os
from dotenv import load_dotenv
from functools import lru_cache
from embed_text_onnx import cached_embed_text

load_dotenv()

def semantic_search(
    query: str,
    limit: int = 100,
    gender: str | None = None,
    price_max: float | None = None
) -> list[dict]:

    # Step 1: embed the query
    query_vec = list(cached_embed_text(query))

    # Step 2: build filters
    filters = ["p.in_stock = TRUE", "p.active = TRUE"]
    params = [str(query_vec)]

    if gender:
        filters.append("p.gender = %s")
        params.append(gender)
    if price_max:
        filters.append("p.price <= %s")
        params.append(price_max)

    where = " AND ".join(filters)
    params.append(str(query_vec))
    params.append(limit)

    # Step 3: vector similarity search
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()

    cur.execute(f"""
        SELECT
            p.id, p.name, p.brand, p.price,
            p.image_url, p.affiliate_url, p.category,
            1 - (e.embedding <=> %s::vector) AS similarity
        FROM product_embeddings e
        JOIN products p ON p.id = e.product_id
        WHERE {where}
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
    """, params)

    cols = ['id','name','brand','price','image_url',
            'affiliate_url','category','similarity']
    results = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return results