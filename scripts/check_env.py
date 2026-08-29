#!/usr/bin/env python3
"""check_env.py -- diagnoses DATABASE_URL without ever printing it.

    python check_env.py
"""
import pathlib
import re

API_DIR = pathlib.Path(__file__).resolve().parent.parent / "api"
env_path = API_DIR / ".env"

if not env_path.exists():
    print(f"No file at {env_path}")
    raise SystemExit

lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
db_lines = [
    (i + 1, l) for i, l in enumerate(lines)
    if l.strip().startswith("DATABASE_URL") and "=" in l
]

print(f"DATABASE_URL defined on {len(db_lines)} line(s): "
      f"{[n for n, _ in db_lines]}")
if len(db_lines) > 1:
    print("  ^ MORE THAN ONE. Delete all but the correct one -- "
          "the last one in the file is the one actually used.")

for lineno, line in db_lines:
    value = line.split("=", 1)[1].strip()
    has_bracket = "[" in value or "]" in value
    has_placeholder = "YOUR-PASSWORD" in value
    m = re.search(r"postgres\.[^:]+:([^@]*)@", value) or re.search(r"postgres:([^@]*)@", value)
    pw_len = len(m.group(1)) if m else None
    host_m = re.search(r"@([^:/]+)", value)
    port_m = re.search(r":(\d+)/", value)

    print(f"\n  line {lineno}:")
    print(f"    contains literal brackets [ ]:      {has_bracket}")
    print(f"    contains literal 'YOUR-PASSWORD':   {has_placeholder}")
    print(f"    password segment length:            {pw_len}")
    print(f"    host:                                {host_m.group(1) if host_m else '???'}")
    print(f"    port:                                {port_m.group(1) if port_m else '???'}")

    # A clean URL ends in /postgres with nothing after it. Anything trailing
    # (a stray pasted command, extra whitespace, etc.) breaks the DSN parser
    # in confusing ways -- this is safe to print since it's past the
    # password, at the very end of the string.
    tail_m = re.search(r"/postgres(.*)$", value)
    trailing = tail_m.group(1) if tail_m else None
    if trailing:
        print(f"    TRAILING TEXT AFTER '/postgres': {trailing!r}")
        print(f"    -> This is almost certainly the problem. Delete "
              f"everything after 'postgres' on this line.")

    if has_bracket or has_placeholder:
        print("    -> STILL A PLACEHOLDER. Fix this line.")
    elif pw_len in (None, 0):
        print("    -> Password segment looks EMPTY or the URL shape is wrong.")
    elif host_m and "pooler.supabase.com" in host_m.group(1) and port_m and port_m.group(1) == "5432":
        print("    -> Shape looks correct (pooler host, port 5432, password present).")
    else:
        print("    -> Shape looks unusual, double check host/port.")