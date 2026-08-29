"""
api/dry_run_filters.py -- report what the exclusion rules WOULD remove.

Touches no database. Run it, read the counts and samples, adjust the rules,
run it again. Only once the numbers look right do the rules go into ingest.py.

Usage:
    python dry_run_filters.py feeds/23351-54839-en_US-M_S_US.csv
    python dry_run_filters.py feeds/23351-54839-en_US-M_S_US.csv --keep-lingerie
"""

import argparse
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

# ── Rules under test ─────────────────────────────────────────────────────────
# Matched case-insensitively against merchant_category.

# Whole top-level sections to drop. Prefix match, so it catches every
# sub-category without enumerating hundreds of strings.
EXCLUDE_CATEGORY_PREFIXES = ("home",)

# Substring matches anywhere in the category path.
EXCLUDE_CATEGORY_CONTAINS = (
    "school", "baby", "pramsuit", "pre-walker", "bib",
    "sleepsuit", "muslin", "puddlesuit",
)

# Applied only when lingerie is being excluded.
LINGERIE_TERMS = (
    "lingerie", "underwear", "bra", "knicker", "thong", "brief",
    "plunge", "basque", "suspender", "shaping", "camisole", "chemise",
    "babydoll", "slip", "nightie", "bandeau", "hipster", "boxer", "trunk",
)

# Matched against product_name. Age markers are a far more reliable kidswear
# signal than category is -- "(2-18 Yrs)", "(7lbs-1 Yrs)", "(6-16 Yrs)".
EXCLUDE_NAME_PATTERNS = (
    r"\(\s*\d+\s*-\s*\d+\s*Yrs?\s*\)",
    r"\(\s*\d+\s*lbs",
    r"\(\s*\d+\s*-\s*\d+\s*Mths?\s*\)",
)
# ─────────────────────────────────────────────────────────────────────────────


def cat_prefix_mask(cats: pd.Series) -> pd.Series:
    low = cats.fillna("").str.lower().str.strip()
    mask = pd.Series(False, index=cats.index)
    for p in EXCLUDE_CATEGORY_PREFIXES:
        mask |= low.str.startswith(p)
    return mask


def cat_contains_mask(cats: pd.Series, terms) -> pd.Series:
    low = cats.fillna("").str.lower()
    mask = pd.Series(False, index=cats.index)
    for t in terms:
        mask |= low.str.contains(re.escape(t), regex=True, na=False)
    return mask


def name_mask(names: pd.Series) -> pd.Series:
    mask = pd.Series(False, index=names.index)
    for p in EXCLUDE_NAME_PATTERNS:
        mask |= names.fillna("").str.contains(p, case=False, regex=True, na=False)
    return mask


def report(label: str, mask: pd.Series, df: pd.DataFrame, total: int) -> None:
    n = int(mask.sum())
    print(f"\n{'=' * 72}")
    print(f"{label}: {n:,} rows ({n / total:.1%})")
    print("=" * 72)
    if n == 0:
        return
    hit = df[mask]
    print("\n  Top categories caught:")
    for cat, c in hit["merchant_category"].value_counts().head(12).items():
        print(f"    {c:>6,}  {cat}")
    print("\n  Sample product names:")
    for nm in hit["product_name"].dropna().head(8):
        print(f"    {nm[:90]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("feed", help="Path to the feed CSV, relative to this file")
    ap.add_argument("--keep-lingerie", action="store_true",
                    help="Do not treat lingerie/underwear as excluded")
    args = ap.parse_args()

    path = HERE / args.feed
    df = pd.read_csv(path, dtype=str, low_memory=False,
                     usecols=["product_name", "merchant_category", "merchant_name"])
    total = len(df)
    print(f"\nFeed: {path.name}")
    print(f"Rows: {total:,}")

    m_prefix = cat_prefix_mask(df["merchant_category"])
    m_contains = cat_contains_mask(df["merchant_category"], EXCLUDE_CATEGORY_CONTAINS)
    m_name = name_mask(df["product_name"])
    m_lingerie = cat_contains_mask(df["merchant_category"], LINGERIE_TERMS)

    report("RULE 1 -- category prefix (home goods)", m_prefix, df, total)
    report("RULE 2 -- category contains (kidswear/school)", m_contains, df, total)
    report("RULE 3 -- product name age markers", m_name, df, total)
    report("RULE 4 -- lingerie/underwear", m_lingerie, df, total)

    combined = m_prefix | m_contains | m_name
    if not args.keep_lingerie:
        combined |= m_lingerie

    kept = total - int(combined.sum())
    print(f"\n{'=' * 72}")
    print("COMBINED")
    print("=" * 72)
    print(f"  Removed: {int(combined.sum()):,} ({combined.mean():.1%})")
    print(f"  Kept:    {kept:,}")
    print(f"  Lingerie: {'KEPT' if args.keep_lingerie else 'REMOVED'}")

    print("\n  Largest categories SURVIVING the filters:")
    for cat, c in df[~combined]["merchant_category"].value_counts().head(20).items():
        print(f"    {c:>6,}  {cat}")

    # The check that matters most: what got caught that shouldn't have.
    print("\n  Categories caught by MORE THAN ONE rule (sanity check):")
    overlap = (m_prefix.astype(int) + m_contains.astype(int)
               + m_name.astype(int) + m_lingerie.astype(int)) > 1
    if overlap.any():
        for cat, c in df[overlap]["merchant_category"].value_counts().head(8).items():
            print(f"    {c:>6,}  {cat}")
    else:
        print("    none")


if __name__ == "__main__":
    main()