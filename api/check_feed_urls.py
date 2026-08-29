"""
api/check_feed_urls.py -- are the image URLs in a FRESH feed actually alive?

Reads the CSV directly (not the database), samples rows per merchant, and
probes both image columns. This distinguishes "our stored URLs are stale"
from "the feed itself ships dead URLs".

Usage:
    python check_feed_urls.py feeds/datafeed_3015285.csv
    python check_feed_urls.py feeds/datafeed_3015285.csv --merchant Cerqular --n 40
"""

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")


def probe(session, url) -> str:
    if not isinstance(url, str) or not url:
        return "no-url"
    try:
        r = session.get(url, timeout=15, stream=True)
        code = r.status_code
        size = r.headers.get("Content-Length", "?")
        r.close()
        return f"HTTP {code}" + (f" ({int(size) // 1024}KB)" if size.isdigit() else "")
    except requests.exceptions.Timeout:
        return "timeout"
    except Exception as e:
        return type(e).__name__


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("feed")
    ap.add_argument("--merchant", help="Restrict to one merchant name (substring)")
    ap.add_argument("--n", type=int, default=25, help="Rows to probe per merchant")
    args = ap.parse_args()

    df = pd.read_csv(HERE / args.feed, dtype=str, low_memory=False,
                     usecols=["merchant_name", "aw_image_url",
                              "merchant_image_url", "last_updated"])
    print(f"Feed: {args.feed}")
    print(f"Rows: {len(df):,}")

    if "last_updated" in df.columns:
        lu = df["last_updated"].dropna()
        if len(lu):
            print(f"last_updated range: {lu.min()}  ->  {lu.max()}")

    if args.merchant:
        df = df[df["merchant_name"].str.contains(args.merchant, case=False, na=False)]
        merchants = [args.merchant]
    else:
        merchants = df["merchant_name"].value_counts().head(5).index.tolist()

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    for m in merchants:
        sub = df[df["merchant_name"].str.contains(m, case=False, na=False)]
        if sub.empty:
            continue
        sample = sub.sample(min(args.n, len(sub)), random_state=1)
        hires_t, proxy_t = Counter(), Counter()
        first_dead = None

        for r in sample.itertuples(index=False):
            h = probe(session, r.merchant_image_url)
            p = probe(session, r.aw_image_url)
            hires_t[h] += 1
            proxy_t[p] += 1
            if first_dead is None and not h.startswith("HTTP 200"):
                first_dead = r.merchant_image_url

        print(f"\n{'=' * 68}\n{m}  ({len(sub):,} rows in feed)\n{'=' * 68}")
        print("  merchant_image_url:")
        for k, v in hires_t.most_common():
            print(f"      {v:>3}  {k}")
        print("  aw_image_url (proxy):")
        for k, v in proxy_t.most_common():
            print(f"      {v:>3}  {k}")
        if first_dead:
            print(f"  example dead: {str(first_dead)[:120]}")

    print("\nInterpretation:")
    print("  hires mostly 200  -> our DB URLs were stale; re-ingest fixes it")
    print("  hires mostly 404  -> the FEED ships dead URLs; use the proxy for")
    print("                       this merchant, or drop the merchant")


if __name__ == "__main__":
    main()