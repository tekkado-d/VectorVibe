#!/usr/bin/env python3
"""explain_search.py -- see exactly where a search spends its time.

Runs EXPLAIN (ANALYZE, BUFFERS) on the real search query using a real
embedded vector for the text you give it. This shows the actual cost of
each stage -- index scan, join, filter, sort -- instead of guessing.

    python explain_search.py "mechanic"
    python explain_search.py "mechanic" --probes 5
    python explain_search.py "mechanic" --probes 1
"""
import argparse
import os
import pathlib
import sys

import psycopg2
from dotenv import load_dotenv

API_DIR = pathlib.Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from query import query_vector  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--probes", type=int,
                     default=int(os.getenv("IVFFLAT_PROBES", "10")))
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    print(f"Embedding '{args.query}' ...")
    vec = query_vector(args.query, lookup=None)  # bypass expansion cache -- we
                                                  # want the raw index/join cost

    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    cur.execute("SET LOCAL ivfflat.probes = %s", (args.probes,))
    cur.execute(
        """
        EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
        SELECT p.id, p.name, p.brand, p.price,
               1 - (e.embedding <=> %s::vector) AS similarity
        FROM product_embeddings e
        JOIN products p ON p.id = e.product_id
        WHERE p.in_stock = TRUE AND p.active = TRUE
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
        """,
        (str(vec), str(vec), args.limit),
    )

    print(f"\n--- EXPLAIN ANALYZE, probes={args.probes} ---\n")
    for row in cur.fetchall():
        print(row[0])

    conn.rollback()  # EXPLAIN needs nothing committed; keeps SET LOCAL scoped
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()