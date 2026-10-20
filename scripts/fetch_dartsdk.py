#!/usr/bin/env python3
"""Download+extract Dart SDK source tarball for the Dart VM build.

Used by build.ps1 (and CI) because plain `git clone` of dart-lang/sdk is
unreliable through some networks; the codeload tarball is a single HTTP
download. Files are extracted to <dest>/ (contents of sdk-<ver>/).

Usage: python scripts/fetch_dartsdk.py <version> <dest-dir> [cache-dir]
"""
import os
import sys
import tarfile
import time
import urllib.request

URL = "https://codeload.github.com/dart-lang/sdk/tar.gz/refs/tags/{ver}"


def download(url: str, out: str) -> None:
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part"
    last_err = None
    for attempt in range(1, 4):
        try:
            t0 = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": "fiet-win-dart-build"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                total = 0
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
                    if total % (16 << 20) < (1 << 20):
                        print(f"  downloaded {total / 1048576:.1f} MiB ({time.time()-t0:.0f}s)", flush=True)
            os.replace(tmp, out)
            print(f"  saved {out} ({os.path.getsize(out)/1048576:.1f} MiB, {time.time()-t0:.0f}s)", flush=True)
            return
        except Exception as e:  # noqa: BLE001 - retry network errors
            last_err = e
            print(f"  attempt {attempt} failed: {e!r}", flush=True)
            time.sleep(3 * attempt)
    raise RuntimeError(f"download failed after retries: {last_err!r}")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    ver, dest = sys.argv[1], sys.argv[2]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache = sys.argv[3] if len(sys.argv) > 3 else os.path.join(root, "build", "cache")
    tar_path = os.path.join(cache, f"dart-sdk-{ver}.tar.gz")
    if not os.path.isfile(tar_path) or os.path.getsize(tar_path) < 10 * 1024 * 1024:
        download(URL.format(ver=ver), tar_path)
    if os.path.isfile(os.path.join(dest, "runtime", "vm", "version_in.cc")):
        print(f"  {dest} already populated, skip extract")
        return 0
    print(f"  extracting {tar_path} -> {dest}", flush=True)
    os.makedirs(dest, exist_ok=True)
    t0 = time.time()
    with tarfile.open(tar_path, "r:gz") as tf:
        prefix = f"sdk-{ver}/"
        for member in tf:
            if not member.name.startswith(prefix) or not (member.isfile() or member.isdir()):
                continue
            member.name = member.name[len(prefix):]
            if not member.name:
                continue
            tf.extract(member, dest)
    print(f"  extracted in {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
