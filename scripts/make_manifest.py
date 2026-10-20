#!/usr/bin/env python3
"""Build manifest.json for fiet-win-dart engine packages.

Scans dist/dartvm-<version>-windows-x64/ directories (produced by build.ps1),
reads the DLL name / SHA256SUMS / zip, and emits a machine-readable manifest for
FIET (Windows engine discovery/download):

{
  "schema": 1,
  "platform": "windows-x64",
  "hostArch": "x86_64",
  "targetAbi": "android-arm64",
  "engineApi": {"exports": ["blutter_analyze", "fler_engine_info"], "callingConvention": "cdecl"},
  "engines": [{"dartVersion": "3.12.2", "dll": "...", "file": "...zip",
               "url": "...", "sha256": "...", "sizeBytes": N,
               "runtimeDeps": ["capstone.dll", "icuuc73.dll", "icudt73.dll"]}]
}

Usage: python scripts/make_manifest.py [--base-url URL] [--version-tag TAG]
"""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(HERE, "dist")
RUNTIME_DEPS = ["capstone.dll", "icuuc73.dll", "icudt73.dll"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="",
                    help="release/download base URL, e.g. https://github.com/<owner>/<repo>/releases/download/<tag>")
    ap.add_argument("--version-tag", default="v0.1.0-poc")
    ap.add_argument("--out", default=os.path.join(HERE, "manifest.json"))
    args = ap.parse_args()

    engines = []
    if os.path.isdir(DIST):
        for name in sorted(os.listdir(DIST)):
            m = re.match(r"^dartvm-([0-9][0-9A-Za-z.\-]*)-windows-x64$", name)
            if not m:
                continue
            d = os.path.join(DIST, name)
            version = m.group(1)
            dll = next((f for f in os.listdir(d) if f.endswith("_windows_x64.dll")), None)
            if not dll:
                print(f"[manifest] WARN: no DLL in {d}, skip")
                continue
            zip_name = name + ".zip"
            zip_path = os.path.join(DIST, zip_name)
            url = ""
            size = 0
            digest = ""
            if os.path.isfile(zip_path):
                url = (args.base_url.rstrip("/") + "/" + zip_name) if args.base_url else zip_name
                size = os.path.getsize(zip_path)
                digest = sha256(zip_path)
            else:
                digest = sha256(os.path.join(d, dll))
            engines.append({
                "dartVersion": version,
                "dll": dll,
                "file": zip_name if os.path.isfile(zip_path) else dll,
                "url": url,
                "sha256": digest,
                "sizeBytes": size,
                "runtimeDeps": [dep for dep in RUNTIME_DEPS if os.path.isfile(os.path.join(d, dep))],
            })
    manifest = {
        "schema": 1,
        "name": "fiet-win-dart engines",
        "platform": "windows-x64",
        "hostArch": "x86_64",
        "targetAbi": "android-arm64",
        "dartTarget": {"os": "android", "arch": "arm64", "compressedPointers": True},
        "engineApi": {
            "exports": ["blutter_analyze", "fler_engine_info"],
            "callingConvention": "cdecl",
            "signature": "int blutter_analyze(const char* libapp_so, const char* db_path, const char* out_dir)",
        },
        "releaseTag": args.version_tag,
        "engines": engines,
    }
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"[manifest] wrote {args.out} ({len(engines)} engines)")
    for e in engines:
        print(f"  - dart {e['dartVersion']}: {e['file']} ({e['sizeBytes']} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
