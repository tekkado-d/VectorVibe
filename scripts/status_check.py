#!/usr/bin/env python3
"""
status_check.py -- one command, ground truth, no assumptions.

Run this from scripts/. It checks what's ACTUALLY in place, not what we
think we discussed:

  1. Which version of each api/*.py file is on disk
  2. Which keys exist in api/.env (never prints values)
  3. Whether the API is running locally, and what /config reports
  4. Database: search_log columns, query_expansions table, RLS status
  5. Which baseline snapshots already exist

    python status_check.py

Paste the full output back and we'll pick up from exactly where you are.
"""

import pathlib
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
API_DIR = SCRIPTS_DIR.parent / "api"
BASELINES_DIR = SCRIPTS_DIR / "baselines"

OK, MISSING, PARTIAL = "[OK]  ", "[--]  ", "[!!]  "


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ── 1. Which code is actually on disk ───────────────────────────────────
def check_files() -> dict:
    section("1. FILES ON DISK")
    found = {}

    main_py = API_DIR / "main.py"
    if not main_py.exists():
        print(f"{MISSING}api/main.py not found")
        found["main"] = "missing"
    else:
        text = main_py.read_text(encoding="utf-8", errors="ignore")
        has_config = '"/config"' in text
        has_bg = "BackgroundTasks" in text
        has_pool = "SimpleConnectionPool" in text
        has_click_fix = "SELECT id FROM search_log" in text
        if has_config and has_bg and has_pool and has_click_fix:
            print(f"{OK}api/main.py -- updated version (pool, /config, click fix)")
            found["main"] = "updated"
        elif has_config or has_bg or has_pool:
            print(f"{PARTIAL}api/main.py -- PARTIALLY updated")
            print(f"       /config endpoint:     {'yes' if has_config else 'NO'}")
            print(f"       BackgroundTasks:       {'yes' if has_bg else 'NO'}")
            print(f"       connection pool:       {'yes' if has_pool else 'NO'}")
            print(f"       /click SQL fix:        {'yes' if has_click_fix else 'NO'}")
            found["main"] = "partial"
        else:
            print(f"{MISSING}api/main.py -- ORIGINAL version, not yet updated")
            found["main"] = "original"

    search_py = API_DIR / "search.py"
    if not search_py.exists():
        print(f"{MISSING}api/search.py not found")
        found["search"] = "missing"
    else:
        text = search_py.read_text(encoding="utf-8", errors="ignore")
        has_probes = "ivfflat.probes" in text
        has_pool = "SimpleConnectionPool" in text
        has_expansion = "expansion_lookup" in text
        has_query_import = "from query import" in text
        if has_probes and has_pool and has_expansion:
            print(f"{OK}api/search.py -- updated version (probes, pool, expansion)")
            found["search"] = "updated"
        elif has_probes or has_pool or has_query_import:
            print(f"{PARTIAL}api/search.py -- PARTIALLY updated")
            print(f"       ivfflat.probes control: {'yes' if has_probes else 'NO'}")
            print(f"       connection pool:        {'yes' if has_pool else 'NO'}")
            print(f"       expansion cache lookup: {'yes' if has_expansion else 'NO'}")
            print(f"       imports query.py:       {'yes' if has_query_import else 'NO'}")
            found["search"] = "partial"
        else:
            print(f"{MISSING}api/search.py -- ORIGINAL version, not yet updated")
            found["search"] = "original"

    query_py = API_DIR / "query.py"
    if query_py.exists():
        print(f"{OK}api/query.py exists")
        found["query"] = "present"
    else:
        print(f"{MISSING}api/query.py NOT FOUND -- required by the updated search.py")
        found["query"] = "missing"

    return found


# ── 2. .env keys present (values never shown) ───────────────────────────
def check_env() -> dict:
    section("2. api/.env -- KEYS PRESENT (values hidden)")
    env_path = API_DIR / ".env"
    found = {}

    if not env_path.exists():
        print(f"{MISSING}api/.env not found")
        return found

    lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    keys = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        keys[k.strip()] = v.strip()

    for key in ["DATABASE_URL", "IVFFLAT_PROBES", "QUERY_TEMPLATE", "QUERY_EXPANSION"]:
        if key in keys:
            flag = OK
            note = ""
            if key == "DATABASE_URL":
                if "[YOUR-PASSWORD]" in keys[key] or "YOUR-PASSWORD" in keys[key]:
                    flag = PARTIAL
                    note = " -- still contains the LITERAL PLACEHOLDER, not a real password"
                elif keys[key].startswith("postgresql"):
                    note = " -- looks like a valid connection string"
            print(f"{flag}{key} is set{note}")
            found[key] = keys[key] if key != "DATABASE_URL" else "set"
        else:
            print(f"{MISSING}{key} is NOT set")
            found[key] = None

    return found


# ── 3. Is the API actually running, and under what config ──────────────
def check_live_api() -> dict:
    section("3. LIVE API (localhost:8000)")
    found = {"running": False}
    try:
        import requests
    except ImportError:
        print(f"{MISSING}'requests' not installed in this environment")
        return found

    try:
        r = requests.get("http://localhost:8000/health", timeout=3)
        if r.status_code == 200:
            print(f"{OK}API is running -- {r.json()}")
            found["running"] = True
        else:
            print(f"{PARTIAL}API responded but with status {r.status_code}")
    except requests.exceptions.RequestException:
        print(f"{MISSING}API is NOT running (or not reachable at :8000)")
        print("       This is fine if you haven't started uvicorn yet.")
        return found

    try:
        r = requests.get("http://localhost:8000/config", timeout=3)
        if r.status_code == 200:
            print(f"{OK}/config responds: {r.json()}")
            found["config"] = r.json()
        else:
            print(f"{MISSING}/config endpoint not found (status {r.status_code})")
            print("       main.py on disk doesn't have it wired up yet, or")
            print("       the running process hasn't picked up the new file.")
    except requests.exceptions.RequestException:
        print(f"{MISSING}/config request failed even though /health worked")

    return found


# ── 4. Database state ────────────────────────────────────────────────────
def check_database() -> dict:
    section("4. DATABASE")
    found = {}
    try:
        import psycopg2
        from dotenv import load_dotenv
        import os
    except ImportError as e:
        print(f"{MISSING}Missing package: {e}")
        return found

    load_dotenv(API_DIR / ".env")
    dsn = os.getenv("DATABASE_URL")
    if not dsn or "[YOUR-PASSWORD]" in dsn:
        print(f"{MISSING}DATABASE_URL is missing or still has the placeholder")
        print("       Skipping all database checks -- fix this first.")
        return found

    try:
        conn = psycopg2.connect(dsn, connect_timeout=5)
    except Exception as e:
        print(f"{MISSING}Could not connect: {e}")
        print("       Check: password correct? using the POOLER host, not")
        print("       the direct db.xxx host? port 6543?")
        return found

    print(f"{OK}Connected successfully")
    cur = conn.cursor()

    # search_log columns
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'search_log'
    """)
    cols = {r[0] for r in cur.fetchall()}
    needed = {"ms_embed", "ms_search", "ms_total", "cache_hit", "n_results"}
    missing = needed - cols
    if not missing:
        print(f"{OK}search_log has all timing columns")
    elif needed & cols:
        print(f"{PARTIAL}search_log missing: {sorted(missing)}")
    else:
        print(f"{MISSING}search_log has NONE of the new timing columns")
    found["search_log_columns"] = sorted(cols)

    # query_expansions table
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'query_expansions'
        )
    """)
    has_table = cur.fetchone()[0]
    print(f"{OK if has_table else MISSING}query_expansions table "
          f"{'exists' if has_table else 'does NOT exist yet'}")
    found["query_expansions_exists"] = has_table

    if has_table:
        cur.execute("""
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE failed IS TRUE) AS failed,
                count(*) FILTER (WHERE failed IS NOT TRUE AND embedding IS NOT NULL) AS ok
            FROM query_expansions
        """)
        total, failed, ok = cur.fetchone()
        found["query_expansions_total"] = total
        if total == 0:
            print(f"{MISSING}query_expansions has 0 rows -- table exists but "
                  f"is empty. Nothing has been written to it yet.")
        else:
            flag = OK if ok > 0 else PARTIAL
            print(f"{flag}query_expansions: {total} rows total "
                  f"({ok} succeeded, {failed} marked failed)")

    # RLS status
    cur.execute("""
        SELECT tablename, rowsecurity FROM pg_tables
        WHERE schemaname = 'public'
        AND tablename IN ('products','product_embeddings','search_log','query_expansions')
    """)
    rls = dict(cur.fetchall())
    for t in ["products", "product_embeddings", "search_log", "query_expansions"]:
        state = rls.get(t)
        if state is True:
            print(f"{OK}RLS enabled on {t}")
        elif state is False:
            print(f"{PARTIAL}RLS DISABLED on {t}")
        else:
            print(f"{MISSING}{t} not found")
    found["rls"] = rls

    cur.close()
    conn.close()
    return found


# ── 5. Existing baseline snapshots ──────────────────────────────────────
def check_baselines() -> list:
    section("5. BASELINE SNAPSHOTS")
    if not BASELINES_DIR.exists():
        print(f"{MISSING}No baselines/ folder yet -- capture 'before' first")
        return []

    snaps = sorted(BASELINES_DIR.glob("*.json"))
    if not snaps:
        print(f"{MISSING}baselines/ exists but is empty")
        return []

    labels = []
    for p in snaps:
        print(f"{OK}{p.name}")
        labels.append(p.stem.split("__", 1)[-1] if "__" in p.stem else p.stem)
    return labels


def main() -> None:
    files = check_files()
    env = check_env()
    live = check_live_api()
    db = check_database()
    baselines = check_baselines()

    section("SUMMARY -- WHAT TO DO NEXT")
    if files.get("main") != "updated" or files.get("search") != "updated" or files.get("query") != "present":
        print("-> The three api/ files aren't all in their updated state yet.")
        print("   This is the first thing to fix.")
    elif env.get("DATABASE_URL") != "set":
        print("-> DATABASE_URL isn't set correctly in api/.env.")
    elif not db.get("query_expansions_exists") or (db.get("search_log_columns") and
          not {"ms_embed","ms_search","ms_total","cache_hit","n_results"} <= set(db["search_log_columns"])):
        print("-> Database migration (ALTER TABLE / CREATE TABLE) hasn't fully run.")
    elif not live.get("running"):
        print("-> Everything on disk looks right, but the API isn't running.")
        print("   Start it: cd api && venv\\Scripts\\activate && "
              "uvicorn main:app --reload --port 8000")
    elif not live.get("config"):
        print("-> API is running but /config isn't responding -- it's likely")
        print("   running an OLD copy of main.py. Stop it fully (Ctrl+C) and")
        print("   restart -- don't rely on --reload picking up big changes.")
    elif "before" not in baselines:
        print("-> Capture a 'before' baseline first, if you haven't:")
        print("   python baseline.py capture before")
    elif "pooled" not in baselines:
        print("-> Everything is in place. Capture the pooling baseline:")
        print("   python baseline.py capture pooled -n \"pool + click fix\"")
        print("   python baseline.py compare before pooled")
    else:
        print("-> Files, database, and API all look correct, and you have")
        print("   'before' and 'pooled' snapshots. Next: set IVFFLAT_PROBES=10,")
        print("   restart, and capture 'probes'.")


if __name__ == "__main__":
    main()