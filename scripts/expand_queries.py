#!/usr/bin/env python3
"""scripts/expand_queries.py

Nightly batch job. Runs on YOUR GPU box, never on Railway.

Reads queries users have actually typed, asks a local LLM to rewrite each into
concrete garment descriptions, embeds those, averages them into one vector,
and stores it. The API then serves that vector with no model call at all.

This is where Layer 2 lives: each phrase is embedded under several templates
and the whole lot averaged. Expensive, but nobody is waiting.

Usage:
    python expand_queries.py            # process the queue
    python expand_queries.py --seed     # pre-expand a starter query list
    python expand_queries.py --limit 50

Prerequisites:
    ollama serve            (running -- installed as a background service)
    ollama pull llama3.1:8b
    pip install ollama
"""

import argparse
import json
import os
import pathlib
import sys

import numpy as np
import ollama
import psycopg2
from dotenv import load_dotenv

# This script lives in scripts/, but embed_text_onnx.py and .env live in
# api/. Without this, `from embed_text_onnx import embed_text` fails with
# ModuleNotFoundError, and load_dotenv() silently finds nothing (it's
# cwd-dependent) -- the same class of bug that broke main.py's env loading
# earlier tonight.
API_DIR = pathlib.Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

# CRITICAL: this must be the SAME encoder that produced your product image
# embeddings, or the stored vectors land in a different space and search
# quality silently collapses. Confirmed identical via check_encoders.py.
from embed_text_onnx import embed_text  # noqa: E402

MODEL = "llama3.1:8b"
BATCH_LIMIT = 200

SYSTEM = """You convert a fashion search query into 4 short visual descriptions
of individual women's garments that match the vibe of the query.

Rules:
- Each description names a SPECIFIC garment type (dress, blazer, trousers...).
- Describe colour, fabric, silhouette and detailing.
- Each description must be its own single string of 3 to 12 words.
- No brand names. No people's names. No film titles. No explanation.
- Describe what a product photograph would show, not what the query means.

Respond with ONLY a JSON object in exactly this shape, no other keys, no
extra text before or after:
{"garments": ["ivory silk slip dress with lace trim", "black tailored wool blazer with structured shoulders", "burgundy velvet midi skirt with side slit", "cream cable-knit oversized jumper"]}"""

# Layer 2. Averaging across templates beats any single template. Note this
# is a SEPARATE set of templates from query.py's Layer 1 -- and applied to
# already-detailed 8-12 word phrases, not raw short queries, which is why
# tonight's Layer 1 failure (boilerplate overwhelming a 3-word query) is not
# expected to recur here. Worth confirming empirically once this is live.
TEMPLATES = [
    "a product photo of {}",
    "a photo of a woman wearing {}",
    "a fashion catalogue image of {}",
    "{}, studio product shot",
    "a stylish outfit featuring {}",
]

# Seed list: expand these before launch so the cache is warm on day one.
SEED = [
    "american psycho", "clueless", "titanic", "the matrix", "the great gatsby",
    "wes anderson", "blade runner", "succession", "euphoria", "bridgerton",
    "cottagecore", "dark academia", "old money", "coastal grandmother",
    "y2k", "grunge", "minimalist", "maximalist", "goth", "preppy",
    "scientist", "mechanic", "librarian", "analyst", "nurse", "chef",
    "1920s", "1950s", "1970s", "1990s",
    "wedding guest", "job interview", "first date", "festival", "funeral",
    "rainy day in london", "summer in italy", "winter in stockholm",
]


def db():
    # connect_timeout is the whole fix here: psycopg2 has NO timeout by
    # default, so any network hiccup makes this hang forever with no error,
    # requiring a manual Ctrl+C to even notice. 10s fails fast and loud.
    try:
        return psycopg2.connect(os.getenv("DATABASE_URL"), connect_timeout=10)
    except psycopg2.OperationalError as e:
        sys.exit(
            f"\n  Could not connect to the database: {e}\n"
            "  If this was a timeout, it's likely a transient network blip --\n"
            "  just try again. If it fails repeatedly, run status_check.py\n"
            "  first to confirm DATABASE_URL is still good.\n"
        )


def expand(query: str) -> list[str] | None:
    """Ask the local LLM for garment descriptions. None means 'skip this one'."""
    try:
        r = ollama.chat(
            model=MODEL,
            format="json",
            options={"temperature": 0.4},
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": query},
            ],
        )
        raw_text = r["message"]["content"]
    except Exception as e:
        print(f"    LLM call failed: {e}")
        return None

    try:
        raw = json.loads(raw_text)
        if isinstance(raw, list):
            phrases = raw
        elif isinstance(raw, dict):
            phrases = raw.get("garments") or next(iter(raw.values()), None)
        else:
            phrases = None
    except Exception as e:
        print(f"    Could not parse JSON: {e}")
        print(f"    Raw response was: {raw_text[:300]!r}")
        return None

    # This is the check that was missing: without it, a string gets silently
    # iterated character-by-character below (every character fails the word
    # count check, producing a confusing "0/4 passed" with no real reason).
    if not isinstance(phrases, list):
        print(f"    Model returned a {type(phrases).__name__}, not a list of "
              f"garments: {phrases!r}")
        return None

    # Guard rails. A bad expansion is worse than no expansion -- if this
    # rejects, the API falls back to Layer 1 (or raw query), which works.
    clean = [
        p.strip() for p in phrases
        if isinstance(p, str) and 3 <= len(p.split()) <= 15
    ]
    if len(clean) < 3:
        print(f"    Only {len(clean)}/4 phrases passed the 3-15 word filter.")
        print(f"    Raw phrases from model: {phrases}")
        return None
    return clean[:4]


def embed_phrases(phrases: list[str]) -> list[float]:
    """Embed every phrase under every template, average, renormalise.

    Averaging NORMALISED vectors then renormalising is the standard prompt
    ensembling recipe. Averaging raw vectors would let longer phrases with
    bigger magnitudes dominate.
    """
    vecs = []
    for p in phrases:
        for t in TEMPLATES:
            v = np.asarray(embed_text(t.format(p)), dtype=np.float32)
            vecs.append(v / np.linalg.norm(v))
    mean = np.mean(vecs, axis=0)
    return (mean / np.linalg.norm(mean)).tolist()


def queue(conn, limit: int) -> list[str]:
    """Most-searched-first, so a capped run still covers the highest value."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT lower(trim(query)) AS q, count(*) AS n
            FROM search_log
            WHERE length(trim(query)) BETWEEN 2 AND 80
              AND lower(trim(query)) NOT IN (SELECT query FROM query_expansions)
            GROUP BY q
            ORDER BY n DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [r[0] for r in cur.fetchall()]


def store(conn, query: str, phrases: list[str], vec: list[float]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO query_expansions (query, phrases, embedding, model, failed)
            VALUES (%s, %s, %s, %s, FALSE)
            ON CONFLICT (query) DO UPDATE
              SET phrases = EXCLUDED.phrases,
                  embedding = EXCLUDED.embedding,
                  model = EXCLUDED.model,
                  failed = FALSE,
                  created_at = now()
            """,
            (query, phrases, str(vec), MODEL),
        )
    conn.commit()


def mark_failed(conn, query: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO query_expansions (query, phrases, embedding, model, failed)
            VALUES (%s, NULL, NULL, %s, TRUE)
            ON CONFLICT (query) DO UPDATE SET failed = TRUE
            """,
            (query, MODEL),
        )
    conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="expand the seed list")
    ap.add_argument("--limit", type=int, default=BATCH_LIMIT)
    args = ap.parse_args()

    conn = db()
    todo = SEED if args.seed else queue(conn, args.limit)

    if not todo:
        print("Nothing to expand.")
        return

    print(f"Expanding {len(todo)} queries with {MODEL}\n")
    ok = 0
    for i, q in enumerate(todo, 1):
        print(f"[{i:3}/{len(todo)}] {q}")
        phrases = expand(q)
        if not phrases:
            mark_failed(conn, q)
            continue
        for p in phrases:
            print(f"          - {p}")
        store(conn, q, phrases, embed_phrases(phrases))
        ok += 1

    conn.close()
    print(f"\nExpanded {ok}/{len(todo)}. Failures are marked and won't be retried.")


if __name__ == "__main__":
    main()