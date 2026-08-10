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
    price_max: float | None = None,
    price_min: float | None = None,
    category: str | None = None,
    brand: str | None = None,
) -> list[dict]:

    query_vec = list(cached_embed_text(query))

    filters = ["p.in_stock = TRUE", "p.active = TRUE"]
    params = [str(query_vec)]

    if gender and gender != 'all':
        filters.append("p.gender = %s")
        params.append(gender)
    if price_min:
        filters.append("p.price::numeric >= %s")
        params.append(price_min)
    if price_max:
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

    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()

    cur.execute(f"""
        SELECT
            p.id, p.name, p.brand, p.price,
            p.image_url, p.affiliate_url, p.category,
            p.gender,
            1 - (e.embedding <=> %s::vector) AS similarity
        FROM product_embeddings e
        JOIN products p ON p.id = e.product_id
        WHERE {where}
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
    """, params)

    cols = ['id','name','brand','price','image_url',
            'affiliate_url','category','gender','similarity']
    results = [dict(zip(cols, row)) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return results