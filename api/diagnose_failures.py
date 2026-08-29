"""
scripts/diagnose_failures.py -- why are image downloads failing?

Samples products that failed embedding and tries each URL variant, reporting
actual HTTP status codes. Distinguishes dead listings (404) from rate limiting
(429) from a bad resize parameter (400) from slow CDNs (timeout).

Usage:
    python scripts/diagnose_failures.py
    python scripts/diagnose_failures.py --brand Cerqular --n 60
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg2
import requests
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

WIDTH = int(os.getenv("EMBED_TARGET_WIDTH", "512"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")


def resized(url: str) -> str:
    """Same logic as embed_products.resized_url -- kept in sync by hand."""
    if not url:
        return url
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        qs = parse_qs(p.query, keep_blank_values=True)
        if "mediahub.boohoo.com" in host:
            qs["w"] = [str(WIDTH)]
            qs.pop("h", None)
        elif "cdn.shopify.com" in host:
            qs["width"] = [str(WIDTH)]
        elif "marksandspencer.app" in host and "/image/upload/" in p.path:
            path = p.path.replace("/image/upload/", f"/image/upload/w_{WIDTH}/", 1)
            return urlunparse(p._replace(path=path))
        else:
            return url
        return urlunparse(p._replace(query=urlencode(qs, doseq=True)))
    except Exception:
        return url


def probe(session, url: str) -> str:
    """Return a short label describing what happened."""
    if not url:
        return "no-url"
    try:
        r = session.get(url, timeout=12, stream=True)
        code = r.status_code
        r.close()
        return f"HTTP {code}"
    except requests.exceptions.Timeout:
        return "timeout"
    except requests.exceptions.ConnectionError:
        return "conn-error"
    except Exception as e:
        return type(e).__name__


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40, help="How many products to probe")
    ap.add_argument("--brand", help="Restrict to one merchant")
    args = ap.parse_args()

    conn = psycopg2.connect(os.getenv("DATABASE_URL"), connect_timeout=10)
    cur = conn.cursor()

    sql = """SELECT id, brand, image_url_hires, image_url
               FROM products
              WHERE embed_attempts > 0 """
    params = []
    if args.brand:
        sql += " AND brand ILIKE %s"
        params.append(f"%{args.brand}%")
    sql += " ORDER BY random() LIMIT %s"
    params.append(args.n)

    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        print("No failed products found. Have you run the embedder yet?")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    # Three variants, probed one at a time (no concurrency -- we are testing
    # whether the server rejects the request, not how fast it responds).
    tallies = {"hires+resize": Counter(), "hires raw": Counter(),
               "proxy fallback": Counter()}
    examples = {}

    print(f"Probing {len(rows)} failed products...\n")
    for pid, brand, hires, proxy in rows:
        results = {
            "hires+resize": probe(session, resized(hires)),
            "hires raw": probe(session, hires),
            "proxy fallback": probe(session, proxy),
        }
        for k, v in results.items():
            tallies[k][v] += 1
        key = (results["hires+resize"], results["hires raw"])
        if key not in examples:
            examples[key] = (brand, hires)

    for label, counter in tallies.items():
        print(f"{label}:")
        for outcome, n in counter.most_common():
            print(f"    {n:>4}  {outcome}")
        print()

    print("Example URLs by outcome (resized, raw):")
    for (a, b), (brand, url) in list(examples.items())[:8]:
        print(f"  [{a} / {b}]  {brand}")
        print(f"    {str(url)[:130]}")

    print("\nReading the result:")
    print("  raw 200 but resized 400/404 -> the resize param is the problem")
    print("  both 404                    -> dead listings, a catalogue issue")
    print("  429 anywhere                -> rate limiting, lower EMBED_WORKERS")
    print("  timeouts                    -> slow CDN, raise HTTP_TIMEOUT")


if __name__ == "__main__":
    main()