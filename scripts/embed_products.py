"""
scripts/embed_products.py -- bulk GPU image embedder.

LOCAL GPU ONLY. Never runs on Railway.

Changes from the previous version:
  * Model config comes from .env (CLIP_MODEL / CLIP_PRETRAINED) so this script,
    embed_gpu.py, export_text_encoder.py and search.py cannot drift apart.
  * Every row is stamped with model_tag -- a vector's provenance now lives in
    the database instead of being implicit and unverifiable.
  * Embeds from products.image_url_hires (merchant CDN original) in preference
    to image_url (Awin's ~200px proxy), with CDN-side resizing to a sane width.
  * Records actual pixel dimensions, so a future low-resolution feed is one
    query away from being noticed rather than silently degrading search.
  * Retries transient HTTP failures; counts persistent ones in
    products.embed_attempts so dead URLs stop being retried on every run.
  * --sample lets you A/B two model configs over an identical product set
    before committing to a full overnight run.

Usage:
    python scripts/embed_products.py                 # everything missing
    python scripts/embed_products.py --sample 2000   # deterministic subset
    python scripts/embed_products.py --limit 500     # smoke test
    python scripts/embed_products.py --retry-failed  # reset attempt counters
"""

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg2
import psycopg2.extras
import requests
import torch
from dotenv import load_dotenv
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import open_clip

# Anchor paths to this file, never the working directory. Relative paths have
# bitten this project more than once.
API_DIR = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

# -- Config -------------------------------------------------------------------
MODEL_NAME = os.getenv("CLIP_MODEL", "ViT-B-16")
PRETRAINED = os.getenv("CLIP_PRETRAINED", "laion2b_s34b_b88k")
MODEL_TAG = f"{MODEL_NAME}/{PRETRAINED}"

BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "128"))
DOWNLOAD_WORKERS = int(os.getenv("EMBED_WORKERS", "32"))

# CLIP resizes to 224x224 internally, so anything past ~2x that is bandwidth
# spent on pixels the model throws away. 512 is headroom without waste.
TARGET_WIDTH = int(os.getenv("EMBED_TARGET_WIDTH", "512"))

# Below this an image carries too little detail to produce a useful vector.
# A garbage vector is worse than a missing one -- it still competes for rank.
MIN_PIXELS = int(os.getenv("EMBED_MIN_PIXELS", "150"))

MAX_ATTEMPTS = 3
HTTP_TIMEOUT = 12

# Some merchant CDNs reject the default python-requests user agent outright.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
# -----------------------------------------------------------------------------


# -- HTTP session, one per thread ---------------------------------------------
# Reusing a session keeps TCP/TLS alive between downloads instead of
# renegotiating per image. Sessions aren't thread-safe, hence thread-local.
_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT})
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=DOWNLOAD_WORKERS)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _local.session = s
    return s


# -- CDN-side resizing --------------------------------------------------------
def resized_url(url: str, width: int = TARGET_WIDTH) -> str:
    """Ask the CDN for a sensible size instead of pulling full originals.

    Turns roughly 60GB of downloads into roughly 8GB across the catalogue.
    Unrecognised hosts pass through untouched -- never guess at a resize
    scheme you have not verified in a browser first.
    """
    if not url:
        return url
    try:
        parts = urlparse(url)
        host = parts.netloc.lower()
        qs = parse_qs(parts.query, keep_blank_values=True)

        if "mediahub.boohoo.com" in host:
            qs["w"] = [str(width)]
            qs.pop("h", None)
        elif "cdn.shopify.com" in host:
            qs["width"] = [str(width)]
        elif "marksandspencer.app" in host and "/image/upload/" in parts.path:
            path = parts.path.replace("/image/upload/", f"/image/upload/w_{width}/", 1)
            return urlunparse(parts._replace(path=path))
        else:
            return url

        return urlunparse(parts._replace(query=urlencode(qs, doseq=True)))
    except Exception:
        return url


# -- Model --------------------------------------------------------------------
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Model:  {MODEL_TAG}")
print(f"Device: {device}")
if device == "cpu":
    print("  WARNING: no CUDA device found. This will be extremely slow.")

model, _, preprocess = open_clip.create_model_and_transforms(
    MODEL_NAME, pretrained=PRETRAINED
)
model = model.to(device)
model.eval()

_dim = model.visual.output_dim
print(f"Output dimensions: {_dim}")
if _dim != 512:
    sys.exit(
        f"ABORT: model outputs {_dim} dims but the column is vector(512).\n"
        "Changing dimensions needs a schema migration. Pick a 512-dim model."
    )


# -- Download + preprocess ----------------------------------------------------
def download_one(args):
    """Return (product_id, tensor, width, height, error).

    Tries the hi-res merchant URL first, falls back to Awin's proxy. The
    fallback matters: merchant CDNs 404 and hotlink-block independently of
    Awin's, so a broken original should degrade to a thumbnail, not to nothing.
    """
    product_id, url_hires, url_fallback = args
    last_error = "no usable url"

    for url in (url_hires, url_fallback):
        if not url:
            continue
        try:
            r = _session().get(resized_url(url), timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            if len(r.content) < 1024:
                raise ValueError(f"empty response: {len(r.content)} bytes")
            img = Image.open(BytesIO(r.content))
            w, h = img.size

            if min(w, h) < MIN_PIXELS:
                raise ValueError(f"image too small: {w}x{h}")

            tensor = preprocess(img.convert("RGB"))
            return (product_id, tensor, w, h, None)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"[:200]
            continue

    return (product_id, None, None, None, last_error)


def embed_batch(batch_rows):
    """Download in parallel, then embed the whole batch in a single GPU call."""
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        results = list(executor.map(download_one, batch_rows))

    good = [r for r in results if r[1] is not None]
    bad_ids = [r[0] for r in results if r[1] is None]

    if not good:
        return [], bad_ids

    tensors = torch.stack([r[1] for r in good]).to(device)
    with torch.no_grad():
        vecs = model.encode_image(tensors)
        vecs = vecs / vecs.norm(dim=-1, keepdim=True)
    vecs = vecs.cpu().tolist()

    embedded = [(r[0], vec, r[2], r[3]) for r, vec in zip(good, vecs)]
    return embedded, bad_ids


# -- Main ---------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Bulk GPU image embedder.")
    ap.add_argument("--limit", type=int, help="Only process N products (smoke test)")
    ap.add_argument("--sample", type=int,
                    help="Deterministic subset of N products, for A/B comparing "
                         "model configs over an identical product set")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Reset embed_attempts to 0 before running")
    args = ap.parse_args()

    # connect_timeout: without it a network hiccup hangs silently forever
    # rather than erroring. Learned the hard way in expand_queries.py.
    conn = psycopg2.connect(os.getenv("DATABASE_URL"), connect_timeout=10)
    cur = conn.cursor()

    if args.retry_failed:
        cur.execute("UPDATE products SET embed_attempts = 0 WHERE embed_attempts > 0")
        conn.commit()
        print(f"Reset embed_attempts on {cur.rowcount:,} products.")

    # "Missing an embedding" now means "missing one FOR THIS MODEL" -- which is
    # exactly what makes the side-by-side, zero-downtime migration possible.
    sql = """
        SELECT p.id, p.image_url_hires, p.image_url
          FROM products p
          LEFT JOIN product_embeddings e
            ON e.product_id = p.id AND e.model_tag = %s
         WHERE e.product_id IS NULL
           AND p.active = TRUE
           AND p.embed_attempts < %s
           AND COALESCE(p.image_url_hires, p.image_url) IS NOT NULL
    """
    params = [MODEL_TAG, MAX_ATTEMPTS]

    if args.sample:
        # md5 of the id is stable across runs, so two model configs see the
        # identical products -- otherwise the comparison proves nothing.
        sql += " ORDER BY md5(p.id::text) LIMIT %s"
        params.append(args.sample)
    else:
        sql += " ORDER BY p.id"
        if args.limit:
            sql += " LIMIT %s"
            params.append(args.limit)

    cur.execute(sql, params)
    rows = cur.fetchall()
    total = len(rows)
    print(f"\nProducts to embed under {MODEL_TAG}: {total:,}")
    if total == 0:
        print("Nothing to do.")
        cur.close()
        conn.close()
        return

    done = failed = 0
    dims = []
    start = time.time()

    try:
        for i in range(0, total, BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            embedded, bad_ids = embed_batch(batch)

            if embedded:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO product_embeddings
                        (product_id, model_tag, embedding, img_width, img_height)
                    VALUES %s
                    ON CONFLICT (product_id, model_tag) DO UPDATE SET
                        embedding  = EXCLUDED.embedding,
                        img_width  = EXCLUDED.img_width,
                        img_height = EXCLUDED.img_height
                """, [(pid, MODEL_TAG, str(v), w, h) for pid, v, w, h in embedded])
                done += len(embedded)
                dims.extend(min(w, h) for _, _, w, h in embedded)

            if bad_ids:
                cur.execute(
                    "UPDATE products SET embed_attempts = embed_attempts + 1 "
                    "WHERE id = ANY(%s)", (bad_ids,)
                )
                failed += len(bad_ids)

            # Per-batch commit: safe to Ctrl+C without losing completed work.
            conn.commit()

            seen = i + len(batch)
            elapsed = time.time() - start
            rate = done / elapsed if elapsed else 0
            eta = (total - seen) / rate / 3600 if rate else 0
            med = sorted(dims)[len(dims) // 2] if dims else 0
            print(f"  {seen:,}/{total:,} -- {done:,} ok, {failed:,} failed -- "
                  f"{rate * 3600:,.0f}/hr -- median {med}px -- ~{eta:.1f}h left")

    except KeyboardInterrupt:
        print("\nInterrupted. Work up to the last batch is committed; "
              "re-run to resume where it stopped.")

    cur.close()
    conn.close()

    print(f"\nComplete: {done:,} embedded, {failed:,} failed")
    if dims:
        s = sorted(dims)
        print(f"Smaller image dimension: p10 {s[len(s)//10]}px, "
              f"median {s[len(s)//2]}px, p90 {s[9*len(s)//10]}px")
        if s[len(s) // 2] < 224:
            print("WARNING: median is below CLIP's native 224px. "
                  "Check that image_url_hires is populated and resizing works.")

    print("\nNext: rebuild the ivfflat index (migration_001.sql block 5) using "
          "the final row count, then point search.py at this model_tag.")


if __name__ == "__main__":
    main()