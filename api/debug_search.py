"""
scripts/debug_search.py -- is the problem the encoder, or the index?

Runs the SAME query vector two ways:
  A) exhaustive scan (no index at all) -- ground truth
  B) through whatever index the planner picks

If A is good and B is bad  -> the index is the problem.
If A is ALSO bad           -> the query vector is wrong (encoder/ONNX issue).

Also embeds the query with BOTH PyTorch and ONNX and compares them, so an
encoder mismatch shows up directly rather than by inference.

Usage:
    python scripts/debug_search.py "charcoal double breasted suit"
"""

import os
import sys
from pathlib import Path

import numpy as np
import psycopg2
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

MODEL_TAG = f"{os.getenv('CLIP_MODEL')}/{os.getenv('CLIP_PRETRAINED')}"

query = sys.argv[1] if len(sys.argv) > 1 else "charcoal double breasted suit"
print(f"Query:     {query}")
print(f"model_tag: {MODEL_TAG}\n")

# ── 1. Embed with PyTorch and with ONNX, compare ─────────────────────────────
import embed_gpu
vec_torch = embed_gpu.embed_text(query)

try:
    import embed_text_onnx
    fn = getattr(embed_text_onnx, "embed_text", None) or \
         getattr(embed_text_onnx, "embed_query", None)
    vec_onnx = fn(query)
    a, b = np.array(vec_torch), np.array(vec_onnx)
    cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
    print(f"PyTorch vs ONNX cosine: {cos:.4f}   "
          f"{'OK' if cos > 0.99 else '<-- MISMATCH, the ONNX file is wrong'}\n")
except Exception as e:
    print(f"Could not load ONNX encoder: {e}\n")

conn = psycopg2.connect(os.getenv("DATABASE_URL"), connect_timeout=10)


def run(label: str, use_index: bool, probes: int = 40):
    with conn.cursor() as cur:
        if use_index:
            cur.execute("SET LOCAL ivfflat.probes = %s", (probes,))
        else:
            # Force a full scan: this is the ground truth ranking, ignoring
            # every recall consideration. Slow, but definitive.
            cur.execute("SET LOCAL enable_indexscan = off")
            cur.execute("SET LOCAL enable_bitmapscan = off")
        cur.execute(f"""
            SELECT p.name, p.brand,
                   1 - (e.embedding <=> %s::vector) AS sim
              FROM product_embeddings e
              JOIN products p ON p.id = e.product_id
             WHERE e.model_tag = '{MODEL_TAG}'
               AND p.active AND p.in_stock
             ORDER BY e.embedding <=> %s::vector
             LIMIT 10
        """, (str(vec_torch), str(vec_torch)))
        rows = cur.fetchall()
    print(f"--- {label} ---")
    for name, brand, sim in rows:
        print(f"  {sim:.4f}  {name[:66]}  [{brand[:18]}]")
    print()
    conn.rollback()


run("A. EXHAUSTIVE (no index) -- ground truth", use_index=False)
run("B. VIA INDEX (probes=40)", use_index=True, probes=40)

# ── Which index did the planner actually choose? ─────────────────────────────
with conn.cursor() as cur:
    cur.execute("SET LOCAL ivfflat.probes = 40")
    cur.execute(f"""
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT p.id FROM product_embeddings e
          JOIN products p ON p.id = e.product_id
         WHERE e.model_tag = '{MODEL_TAG}' AND p.active AND p.in_stock
         ORDER BY e.embedding <=> %s::vector LIMIT 10
    """, (str(vec_torch),))
    print("--- PLAN (literal model_tag) ---")
    for (line,) in cur.fetchall():
        if any(k in line for k in ("Index", "Scan", "Time")):
            print("  " + line.strip())
conn.rollback()
conn.close()

print("\nReading it:")
print("  A good, B bad          -> index problem (wrong index chosen, or probes)")
print("  A and B both bad       -> query vector is wrong; check the cosine above")
print("  Plan shows the OLD index (product_embeddings_vector_idx)")
print("                         -> partial index not matching; drop the old one")