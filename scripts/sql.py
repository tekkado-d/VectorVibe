"""
Ad-hoc SQL runner for VectorVibe.

Place at: C:\\dev\\stylesearch\\scripts\\sql.py

Usage (from C:\\dev\\stylesearch, with the venv active):

    python scripts\\sql.py "SELECT count(*) FROM products"
    python scripts\\sql.py -f scripts\\queries\\vendor_audit.sql
    python scripts\\sql.py "SELECT * FROM products LIMIT 5" --csv out.csv

Reads DATABASE_URL from api/.env. Never prints the connection string.
Read-only by default: pass --write to allow anything other than SELECT/WITH/EXPLAIN.
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

# api/.env sits one level up from scripts/, then into api/
ENV_PATH = Path(__file__).resolve().parent.parent / "api" / ".env"
load_dotenv(ENV_PATH)

READ_ONLY_PREFIXES = ("select", "with", "explain", "show", "table")


def run(sql: str, allow_write: bool = False) -> pd.DataFrame | None:
    stripped = sql.strip().lstrip("(").lower()
    if not allow_write and not stripped.startswith(READ_ONLY_PREFIXES):
        sys.exit(
            "Refusing to run a non-read statement without --write.\n"
            f"Statement began with: {stripped.split()[0] if stripped else '(empty)'}"
        )

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        sys.exit(f"DATABASE_URL not found. Looked in: {ENV_PATH}")

    # connect_timeout matters: without it a network hiccup hangs forever
    conn = psycopg2.connect(dsn, connect_timeout=10)
    try:
        if allow_write:
            with conn.cursor() as cur:
                cur.execute(sql)
                conn.commit()
                print(f"OK. Rows affected: {cur.rowcount}")
            return None
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Run SQL against the VectorVibe database.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("sql", nargs="?", help="SQL statement to run")
    src.add_argument("-f", "--file", help="Path to a .sql file to run instead")
    p.add_argument("--csv", help="Also write results to this CSV path")
    p.add_argument("--rows", type=int, default=50, help="Max rows to print (default 50)")
    p.add_argument("--write", action="store_true", help="Allow non-SELECT statements")
    args = p.parse_args()

    sql = Path(args.file).read_text(encoding="utf-8") if args.file else args.sql

    df = run(sql, allow_write=args.write)
    if df is None:
        return

    with pd.option_context(
        "display.max_rows", args.rows,
        "display.max_columns", None,
        "display.width", 200,
        "display.max_colwidth", 60,
    ):
        print(df)
    print(f"\n[{len(df)} rows x {len(df.columns)} columns]")

    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"Written to {args.csv}")


if __name__ == "__main__":
    main()