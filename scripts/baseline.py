#!/usr/bin/env python3
"""
baseline.py -- capture and compare VectorVibe search results.

Run BEFORE and AFTER any change to the query path, so you can see exactly
what moved instead of guessing.

    python baseline.py capture probes -n "ivfflat.probes 1 -> 10"
    python baseline.py list
    python baseline.py compare before probes
    python baseline.py compare              # the two most recent

Snapshots go to ./baselines/<timestamp>__<label>.json and are never
overwritten. Labels resolve to the most recent matching snapshot, so
`compare before probes` does the sensible thing.

Queries live in ./queries.txt (created on first run). Edit that file, not
this script -- each snapshot records the exact list it used, and compare
warns you if two snapshots don't share one.
"""

import argparse
import datetime
import json
import pathlib
import sys
import time

import requests

API = "http://localhost:8000"
TIMEOUT = 30
TOP_N = 10
OUT_DIR = pathlib.Path("baselines")
QUERY_FILE = pathlib.Path("queries.txt")

# Written to queries.txt on first run. Edit the FILE afterwards.
# Each group tests something different, so a change that helps one group and
# wrecks another is immediately visible.
DEFAULT_QUERIES = """\
# VectorVibe baseline queries. One per line. Lines starting with # are ignored.
# Keep the groups -- they are how you spot a change that helps one kind of
# query while quietly breaking another.

# -- literal garments: the CONTROL group. These already work.
# If a change breaks these, revert it.
black slip dress
oversized denim jacket
red midi skirt
cream knit jumper

# -- abstract aesthetics: currently strong
looks like a dog
cottagecore
old money
dark academia

# -- films: mixed, the interesting middle
American Psycho
Clueless
Titanic
The Matrix

# -- people: currently weakest, the main target of Layer 3
Christian Bale
Zendaya
David Bowie

# -- occupations: your typical input style
scientist
mechanic
analyst

# -- situational
something for a wedding
rainy day in london
"""


def load_queries() -> list[str]:
    if not QUERY_FILE.exists():
        QUERY_FILE.write_text(DEFAULT_QUERIES, encoding="utf-8")
        print(f"Created {QUERY_FILE} -- edit it to add your own queries.\n")
    lines = QUERY_FILE.read_text(encoding="utf-8").splitlines()
    return [q.strip() for q in lines if q.strip() and not q.startswith("#")]


def preflight() -> None:
    """Fail fast and loudly if the API isn't up, instead of erroring per query."""
    try:
        requests.get(f"{API}/health", timeout=5)
    except requests.exceptions.RequestException:
        sys.exit(
            f"\n  Cannot reach the API at {API}\n\n"
            "  Start it in a SECOND terminal and leave it running:\n\n"
            "      cd C:\\dev\\stylesearch\\api\n"
            "      venv\\Scripts\\activate\n"
            "      uvicorn main:app --reload --port 8000\n\n"
            "  Wait for 'Application startup complete', check\n"
            "  http://localhost:8000/docs loads, then re-run this.\n\n"
            "  Still refused with the server running? Windows may be\n"
            "  resolving localhost to IPv6. Set API = 'http://127.0.0.1:8000'\n"
        )


def fetch_config() -> dict | None:
    """Ask the API what settings it's running under, so the snapshot is
    self-describing and you can't mislabel a run."""
    try:
        r = requests.get(f"{API}/config", timeout=5)
        return r.json() if r.status_code == 200 else None
    except requests.exceptions.RequestException:
        return None


def capture(label: str, note: str | None) -> None:
    preflight()
    queries = load_queries()
    cfg = fetch_config()

    if cfg is None:
        print("  ! No /config endpoint -- snapshot won't record its settings.")
        print("    Add it to main.py so runs are self-describing.\n")
    else:
        print(f"  config: {json.dumps(cfg, separators=(',', '='))}\n")

    results = {}
    for i, q in enumerate(queries, 1):
        print(f"  [{i:2}/{len(queries)}] {q}", flush=True)
        try:
            t0 = time.perf_counter()
            r = requests.get(
                f"{API}/search", params={"q": q, "limit": TOP_N}, timeout=TIMEOUT
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            r.raise_for_status()
            rows = r.json().get("results", [])[:TOP_N]
        except Exception as e:
            print(f"        FAILED: {e}", file=sys.stderr)
            results[q] = {"error": str(e)}
            continue

        results[q] = {
            "ms": elapsed_ms,
            "results": [
                {
                    "id": p.get("id"),
                    "name": (p.get("name") or "")[:70],
                    "score": round(float(p.get("similarity") or 0), 4),
                }
                for p in rows
            ],
        }

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"{stamp}__{label}.json"
    path.write_text(
        json.dumps(
            {
                "_meta": {
                    "label": label,
                    "note": note,
                    "captured_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "api": API,
                    "config": cfg,
                    "queries": queries,
                },
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\nSaved {len(queries)} queries -> {path}")


def snapshots() -> list[pathlib.Path]:
    # Any .json in here is a snapshot -- not just the new timestamp__label
    # shape. Older captures (e.g. a plain before.json from an earlier
    # version of this script) still need to resolve correctly.
    return sorted(OUT_DIR.glob("*.json")) if OUT_DIR.exists() else []


def show_list() -> None:
    snaps = snapshots()
    if not snaps:
        sys.exit("No snapshots yet. Run: python baseline.py capture before")
    print(f"\n{'label':<16} {'captured':<18} note")
    print("-" * 72)
    for p in snaps:
        m = json.loads(p.read_text()).get("_meta", {})
        print(
            f"{m.get('label', '?'):<16} "
            f"{m.get('captured_at', '?')[:16]:<18} "
            f"{m.get('note') or ''}"
        )
    print()


def resolve(label: str) -> pathlib.Path:
    """Label -> most recent matching snapshot. Exact filename stems also work."""
    snaps = snapshots()
    if not snaps:
        sys.exit("No snapshots yet.")
    exact = [p for p in snaps if p.stem == label]
    if exact:
        return exact[-1]
    matches = [p for p in snaps if p.stem.split("__", 1)[-1] == label]
    if not matches:
        avail = ", ".join(sorted({p.stem.split("__", 1)[-1] for p in snaps}))
        sys.exit(f"No snapshot labelled '{label}'. Available: {avail}")
    return matches[-1]


def config_delta(a: dict, b: dict) -> None:
    ca, cb = (a.get("config") or {}), (b.get("config") or {})
    if not ca and not cb:
        return
    changed = [
        (k, ca.get(k), cb.get(k))
        for k in sorted(set(ca) | set(cb))
        if ca.get(k) != cb.get(k)
    ]
    if changed:
        print("\nconfig changed:")
        for k, old, new in changed:
            print(f"  {k}: {old}  ->  {new}")
    else:
        print("\nconfig identical between these two runs.")
        print("  If results moved anyway, something else changed -- find out what.")


def compare(label_a: str | None, label_b: str | None) -> None:
    if label_a is None or label_b is None:
        snaps = snapshots()
        if len(snaps) < 2:
            sys.exit("Need at least two snapshots to compare.")
        pa, pb = snaps[-2], snaps[-1]
    else:
        pa, pb = resolve(label_a), resolve(label_b)

    a, b = json.loads(pa.read_text()), json.loads(pb.read_text())
    ma, mb = a.get("_meta", {}), b.get("_meta", {})
    ra, rb = a.get("results", {}), b.get("results", {})

    print(f"\n  A: {pa.name}   {ma.get('note') or ''}")
    print(f"  B: {pb.name}   {mb.get('note') or ''}")

    qa, qb = ma.get("queries", []), mb.get("queries", [])
    queries = [q for q in qa if q in qb] or sorted(set(ra) & set(rb))
    if qa != qb:
        print(f"\n  ! query lists differ -- comparing the {len(queries)} in common")

    config_delta(ma, mb)

    print(f"\n{'query':<28} {'kept':>6} {'top1':>6} {'score':>9} {'ms':>10}")
    print("-" * 64)

    overlaps, ms_deltas = [], []
    for q in queries:
        x, y = ra.get(q, {}), rb.get(q, {})
        if "error" in x or "error" in y or not x or not y:
            print(f"{q[:27]:<28} {'ERROR':>6}")
            continue

        ids_a = [i["id"] for i in x["results"]]
        ids_b = [i["id"] for i in y["results"]]
        kept = len(set(ids_a) & set(ids_b))
        overlaps.append(kept)
        top1 = "same" if ids_a[:1] == ids_b[:1] else "NEW"

        avg_a = sum(i["score"] for i in x["results"]) / max(len(x["results"]), 1)
        avg_b = sum(i["score"] for i in y["results"]) / max(len(y["results"]), 1)
        ms_delta = y.get("ms", 0) - x.get("ms", 0)
        ms_deltas.append(ms_delta)

        print(
            f"{q[:27]:<28} {kept:>4}/10 {top1:>6} "
            f"{avg_b - avg_a:>+9.4f} {ms_delta:>+9}ms"
        )

    if overlaps:
        print("-" * 64)
        print(
            f"{'MEAN':<28} {sum(overlaps)/len(overlaps):>4.1f}/10 {'':>6} "
            f"{'':>9} {sum(ms_deltas)/len(ms_deltas):>+9.0f}ms"
        )
        print(
            "\nReading this: 'kept' is how many of A's top-10 survive into B.\n"
            "  10/10 = nothing changed (did your change actually apply?)\n"
            "   6-9  = healthy re-ranking\n"
            "   0-3  = the query moved to a different region of the space.\n"
            "          Good for 'Titanic'. Alarming for 'black slip dress'.\n"
            "\nScore deltas are cosine similarity and are NOT quality -- they only\n"
            "say the vector moved. Open the site and LOOK at the results."
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="snapshot current results")
    cap.add_argument("label", help="e.g. before, probes, pooled, layer1, layer3")
    cap.add_argument("-n", "--note", help="free text describing this run")

    sub.add_parser("list", help="show all snapshots")

    cmp_ = sub.add_parser("compare", help="diff two snapshots")
    cmp_.add_argument("label_a", nargs="?")
    cmp_.add_argument("label_b", nargs="?")

    args = ap.parse_args()
    if args.cmd == "capture":
        capture(args.label, args.note)
    elif args.cmd == "list":
        show_list()
    else:
        compare(args.label_a, args.label_b)


if __name__ == "__main__":
    main()