import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))

import psycopg2
import time
from dotenv import load_dotenv
from embed import embed_image_from_url

load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'api', '.env'))

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

# Find products with no embedding yet
cur.execute("""
    SELECT p.id, p.image_url FROM products p
    LEFT JOIN product_embeddings e ON e.product_id = p.id
    WHERE e.product_id IS NULL AND p.active = TRUE
    ORDER BY p.id
""")
rows = cur.fetchall()
print(f"Products to embed: {len(rows)}")

done = 0
failed = 0

for i, (product_id, image_url) in enumerate(rows):
    vec = embed_image_from_url(image_url)

    if vec:
        cur.execute("""
            INSERT INTO product_embeddings (product_id, embedding)
            VALUES (%s, %s)
            ON CONFLICT (product_id) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                embedded_at = NOW()
        """, (product_id, str(vec)))
        done += 1
    else:
        failed += 1

    if (i + 1) % 100 == 0:
        conn.commit()
        print(f"  {i+1}/{len(rows)} — {done} embedded, {failed} failed")

conn.commit()
cur.close()
conn.close()
print(f"Complete: {done} embedded, {failed} failed")