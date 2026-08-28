"""
api/ingest.py -- Awin CSV -> PostgreSQL.

Save this over C:\\dev\\stylesearch\\api\\ingest.py and run:

    cd C:\\dev\\stylesearch\\api
    python ingest.py

Everything in one file: hi-res image capture, category/name filtering, and the
upsert fixes. Per-rule removal counts print as it runs, so you can see exactly
what each filter did without a separate dry run.
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

# ── Feed registry ────────────────────────────────────────────────────────────
# Paths resolve against THIS FILE, so the script works from any directory.
FEEDS = [
    {
        "filepath": "feeds/23351-54839-en_US-M_S_US.csv",
        "network":  "awin",
        "gender":   None,   # M&S sells all genders under one program name
    },
     {
         "filepath": "feeds/60703-112084-en_US-BoohooUS_25.csv",
         "network":  "awin",
         "gender":   "f",
     },
     {
         "filepath": "feeds/datafeed_3015285.csv",
         "network":  "awin",
         "gender":   None,
     },
     {
         "filepath": "feeds/MyProteinAU21_08_26.csv",
         "network":  "awin",
         "gender":   None,
     },
     {
        "filepath": "feeds/needsNoLabel28-826.csv",
        "network":  "awin",
        "gender":   None,
    },
]

# ── Merchant gender lookup ───────────────────────────────────────────────────
# Known limitation: one merchant maps to one gender, so this cannot represent a
# retailer selling both (Boohoo, M&S). Those fall through to 'unisex', which is
# at least honest. The real fix is a per-row signal from the feed.
MERCHANT_GENDER = {
    "Alberto Nardoni Affiliate Program US":  "m",
    "Cerqular":                              "unisex",
    "boohoo (US & Canada)":                  "f",
    "Emensuits Affiliate Program US":        "m",
    "Brian James":                           "unisex",
    "Fashiontamers US":                      "unisex",
    "CHIKO (US)":                            "f",
    "T.LUXY":                                "f",
    "Some Slight Clothing":                  "unisex",
    "Mustard Seed":                          "f",
    "Viaduct Clothing":                      "unisex",
    "Lightsin UK":                            "unisex",
    "Little Women Lingerie":                 "f",
    "Plusshop UK":                            "unisex",
    "Dima Eyewear (US)":                     "unisex",
    "Plusshop IE":                            "unisex",
    "Needs No Label":                        "unisex",
    "Macian":                                 "unisex",
    "AliExpress PL":                          "unisex",
    "aZengear":                               "unisex",
    "DAME":                                   "f",
    "Workout For Less":                      "unisex",
    "encalife (US & Canada)":                "unisex",
    "EfuiHarlley":                            "unisex",
    "Hamxi":                                  "unisex",
    "Fang Accessories":                      "unisex",
    "Opulensi Perfumes Lattafa Sapil Anfar": "unisex",
}

# ── Excluded merchants ───────────────────────────────────────────────────────
EXCLUDE_MERCHANTS = {
    "Tooled Up", "Webbs Motorcycles", "Japspeed UK", "4x4 Predator",
    "Santoro Milan", "Lucasgift - US", "AmberPromos - Custom Printed Products",
    "Regina Andrew Detroit", "Boxed2me", "Five Star Direct",
    "Watch Home Awin First", "Chargrilled", "Printerval",
    "Bare Kind Bamboo Socks", "Body Body", "Just Pleasure",
}

# ── Category filters ─────────────────────────────────────────────────────────
# All matched case-insensitively against merchant_category.

# Whole top-level sections. Prefix match catches every sub-category without
# enumerating hundreds of strings (M&S has 400+ distinct category values).
EXCLUDE_CATEGORY_PREFIXES = ("home",)

# Word-boundary matches. \b prevents the classic over-match: a bare "bib"
# substring would hit "bibliography"; a bare "slip" would hit "SLIPPERS".
EXCLUDE_CATEGORY_WORDS = (
    # Kidswear and school uniform
    "school", "baby", "babies", "pramsuit", "pramsuits", "pre-walker",
    "sleepsuit", "sleepsuits", "muslin", "puddlesuit", "puddlesuits",
    "bib", "bibs", "bibshort", "bibshorts",
    # Lingerie, underwear and shapewear.
    # Excluded on business grounds: Awin has rejected applications citing site
    # style, and a wall of on-model lingerie is a real risk with a reviewer.
    # Also a search-quality concern -- CLIP embeds the whole photo including
    # the model, so skin-heavy imagery pulls abstract queries toward it.
    "lingerie", "underwear", "bra", "bras", "knicker", "knickers",
    "thong", "thongs", "brief", "briefs", "plunge", "basque", "basques",
    "suspender", "suspenders", "babydoll", "chemise", "nightie", "nighties",
    "nightshirt", "hipster", "hipsters", "boxer", "boxers", "shapewear",
    "camisole", "bodysuit", "bodysuits", "seamless", "footsie", "footsies",
)

# Exact category matches, for strings where a word-boundary rule would still
# over-reach. "SLIP DRESS" and "SLIP ON" must survive; "FULL SLIP" must not.
EXCLUDE_CATEGORY_EXACT = {
    "clothing > slips",
    "clothing > full slip",
    "clothing > waist slip",
    "clothing > shaping slip",
    "clothing > shaping knickers",
    "clothing > shaping tights",
    "clothing > high leg",
    "clothing > body",
    "clothing > triangle",
    "clothing > bandeau",
    "clothing > shoulder",
    "clothing > soft toy",
    "clothing > hooded towels",
    "clothing > comforter",
}

# Age markers in product_name are a far more reliable kidswear signal than
# category: "(2-18 Yrs)", "(7lbs-1 Yrs)", "(6-16 Yrs)", "(7lbs-12 Mths)".
EXCLUDE_NAME_PATTERNS = (
    r"\(\s*\d+\s*-\s*\d+\s*yrs?\s*\)",
    r"\(\s*\d+\s*lbs",
    r"\(\s*\d+\s*-\s*\d+\s*mths?\s*\)",
)


def _word_regex(words) -> str:
    """One alternation with word boundaries, e.g. \\b(bra|bras|thong)\\b."""
    return r"\b(" + "|".join(re.escape(w) for w in words) + r")\b"


EXCLUDE_WORDS_RE = _word_regex(EXCLUDE_CATEGORY_WORDS)
EXCLUDE_NAME_RE = "|".join(EXCLUDE_NAME_PATTERNS)


# ── Helpers ──────────────────────────────────────────────────────────────────
def parse_stock(val) -> bool:
    """True if in stock, defaulting to True when the field is absent."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return True
    return str(val).strip().lower() in ("true", "1", "yes")


def clean(val):
    """pandas NaN -> None, so Postgres stores NULL not the string 'nan'."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return val


def resolve_gender(feed_gender, merchant_name):
    if feed_gender is not None:
        return feed_gender
    return MERCHANT_GENDER.get(merchant_name, "unisex")


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Drop excluded rows, printing what each rule removed."""
    cat = df["merchant_category"].fillna("").str.lower().str.strip()
    name = df["product_name"].fillna("")

    prefix_mask = pd.Series(False, index=df.index)
    for p in EXCLUDE_CATEGORY_PREFIXES:
        prefix_mask |= cat.str.startswith(p)

    words_mask = cat.str.contains(EXCLUDE_WORDS_RE, regex=True, na=False)
    exact_mask = cat.isin(EXCLUDE_CATEGORY_EXACT)
    name_mask = name.str.contains(EXCLUDE_NAME_RE, case=False, regex=True, na=False)

    for label, mask in (
        ("home goods (category prefix)", prefix_mask),
        ("kidswear + lingerie (category words)", words_mask),
        ("ambiguous categories (exact match)", exact_mask),
        ("kidswear (age marker in name)", name_mask),
    ):
        print(f"    - {label}: {int(mask.sum()):,}")

    drop = prefix_mask | words_mask | exact_mask | name_mask
    return df[~drop]


# ── Ingest one feed ──────────────────────────────────────────────────────────
def ingest_csv(filepath: str, network: str, gender: str | None) -> None:
    path = HERE / filepath
    print(f"\n--- Ingesting: {path.name} ---")

    df = pd.read_csv(path, dtype=str, low_memory=False)
    print(f"  Raw rows: {len(df):,}")

    # merchant_image_url is the merchant's own CDN original -- typically 800px+
    # against aw_image_url's ~200px letterboxed proxy. This is the whole point
    # of this round of work: CLIP resizes to 224x224, so a 200px source was
    # starving it of detail on every single product.
    if "merchant_image_url" not in df.columns:
        print("  NOTE: no merchant_image_url column. Falling back to the "
              "aw_image_url proxy -- expect lower-quality embeddings.")
        df["merchant_image_url"] = None

    before = len(df)
    df = df.dropna(subset=["aw_product_id", "product_name", "aw_deep_link"])
    df = df[df["aw_image_url"].notna() | df["merchant_image_url"].notna()]
    print(f"  After required fields: {len(df):,} ({before - len(df):,} removed)")

    before = len(df)
    df = df[~df["merchant_name"].isin(EXCLUDE_MERCHANTS)]
    print(f"  After merchant exclusions: {len(df):,} ({before - len(df):,} removed)")

    if "merchant_category" in df.columns:
        before = len(df)
        print("  Category / name filters:")
        df = apply_filters(df)
        print(f"  After content filters: {len(df):,} ({before - len(df):,} removed)")

    # Size variants share a product_name; keep one row per name+merchant.
    before = len(df)
    df = df.drop_duplicates(subset=["product_name", "merchant_name"], keep="first")
    print(f"  After dedup: {len(df):,} ({before - len(df):,} removed)")

    if df.empty:
        print("  Nothing left to insert.")
        return

    now = datetime.now(timezone.utc)

    rows = []
    for r in df.itertuples(index=False):
        merchant = clean(getattr(r, "merchant_name", None))
        rows.append((
            clean(r.aw_product_id),
            network,
            clean(r.product_name),
            clean(getattr(r, "description", None)),
            merchant,
            clean(r.aw_image_url),           # image_url       -- Awin proxy
            clean(r.merchant_image_url),     # image_url_hires -- merchant CDN
            clean(r.aw_deep_link),
            clean(getattr(r, "search_price", None)),
            clean(getattr(r, "merchant_category", None)),
            clean(getattr(r, "colour", None)),
            resolve_gender(gender, merchant),
            parse_stock(getattr(r, "in_stock", None)),
            now,
        ))

    print(f"  Upserting {len(rows):,} rows...")

    conn = psycopg2.connect(os.getenv("DATABASE_URL"), connect_timeout=10)
    cur = conn.cursor()

    # gender is deliberately NOT updated on conflict. MERCHANT_GENDER cannot
    # represent a retailer selling both genders, so once you backfill from a
    # real per-row signal, a re-ingest must not overwrite that work.
    execute_values(cur, """
        INSERT INTO products
          (external_id, network, name, description, brand,
           image_url, image_url_hires, affiliate_url, price, category,
           colour, gender, in_stock, last_seen)
        VALUES %s
        ON CONFLICT (external_id, network) DO UPDATE SET
          price           = EXCLUDED.price,
          in_stock        = EXCLUDED.in_stock,
          image_url       = EXCLUDED.image_url,
          image_url_hires = EXCLUDED.image_url_hires,
          affiliate_url   = EXCLUDED.affiliate_url,
          active          = TRUE,
          last_seen       = EXCLUDED.last_seen
    """, rows, page_size=1000)
    conn.commit()
    print("  Upserted.")

    # Products from these merchants NOT seen in this run have left the feed.
    # Cerqular is a resale marketplace -- items are one-of-one and vanish once
    # sold, so without this the site accumulates dead affiliate links.
    merchants = df["merchant_name"].dropna().unique().tolist()
    if merchants:
        cur.execute("""
            UPDATE products
               SET active = FALSE
             WHERE network = %s AND brand = ANY(%s)
               AND active = TRUE AND last_seen < %s
        """, (network, merchants, now))
        print(f"  Marked inactive (gone from feed): {cur.rowcount:,}")
        conn.commit()

    cur.close()
    conn.close()
    print("  Done.")


if __name__ == "__main__":
    for feed in FEEDS:
        if not (HERE / feed["filepath"]).exists():
            print(f"\nSKIPPED (file not found): {feed['filepath']}")
            continue
        ingest_csv(feed["filepath"], feed["network"], feed["gender"])
    print("\nAll feeds processed.")
    print("Do NOT embed yet -- finish the model migration first, then run one "
          "embed pass over the whole catalogue.")