#!/usr/bin/env python3
"""migrate_before.py -- one-time fix for before.json's old file format.

The very first version of baseline.py stored queries directly at the top
level of the JSON file. The current version nests them under "results".
This rewrites before.json into the current shape so `compare` can read it.

Safe to run more than once -- does nothing if already migrated. Keeps a
.bak copy of the original either way.

    python migrate_before.py
"""

import json
import pathlib
import shutil

BASELINES = pathlib.Path(__file__).resolve().parent / "baselines"
target = BASELINES / "before.json"

if not target.exists():
    raise SystemExit(f"No file at {target}")

data = json.loads(target.read_text(encoding="utf-8"))

if "results" in data:
    print("before.json is already in the current format -- nothing to do.")
else:
    meta = data.pop("_meta", {})
    meta.setdefault("queries", list(data.keys()))
    meta.setdefault("label", "before")

    backup = target.with_suffix(".json.bak")
    shutil.copy(target, backup)

    target.write_text(
        json.dumps({"_meta": meta, "results": data}, indent=2),
        encoding="utf-8",
    )
    print(f"Migrated before.json ({len(data)} queries).")
    print(f"Original backed up to {backup.name}")