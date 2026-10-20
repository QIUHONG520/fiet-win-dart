#!/usr/bin/env python3
"""Download the SQLite amalgamation used by the engine DLL.

The engine writes the fler-dart SQLite schema directly (classes/methods/asm_blocks/
pp_entries/strings/analysis_meta/...), so the verification scripts and FIET can
read the DB with sqlite3 / sqlite-jdbc / Android SQLite without changes.

Usage: python scripts/fetch_sqlite.py [dest_dir]
"""
import io
import os
import sys
import zipfile

import requests

SQLITE_ZIP_URL = "https://www.sqlite.org/2024/sqlite-amalgamation-3450100.zip"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    dest = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "third_party", "sqlite")
    os.makedirs(dest, exist_ok=True)
    if os.path.isfile(os.path.join(dest, "sqlite3.c")):
        print(f"[sqlite] already present in {dest}")
        return 0
    print(f"[sqlite] downloading {SQLITE_ZIP_URL}")
    r = requests.get(SQLITE_ZIP_URL, timeout=180)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    base = next(n for n in zf.namelist() if n.endswith("sqlite3.c")).rsplit("/", 1)[0]
    for name in ("sqlite3.c", "sqlite3.h", "sqlite3ext.h"):
        with zf.open(base + "/" + name) as src, open(os.path.join(dest, name), "wb") as out:
            out.write(src.read())
    print(f"[sqlite] extracted to {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
