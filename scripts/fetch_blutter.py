#!/usr/bin/env python3
"""Fetch the pinned upstream blutter tree and prepare it for the Windows build.

The engine is pinned to the same blutter commit fler-dart validated for Dart
2.14-3.12 (`4a60ac648bf448c5a7596437243bcd0b9376fdf0`), then patched by
scripts/prepare_blutter.py. Keeping this in Python (instead of requiring bash)
makes build.ps1 work on plain Windows + Git for Windows without WSL/MSYS.

Usage: python scripts/fetch_blutter.py [dest_dir]
"""
import os
import subprocess
import sys

BLUTTER_REPO = "https://github.com/worawit/blutter.git"
BLUTTER_COMMIT = "4a60ac648bf448c5a7596437243bcd0b9376fdf0"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, cwd=None):
    print("[blutter] " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def git_ok(args, cwd=None):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True).returncode == 0


def main() -> int:
    dest = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "src", "blutter")
    if os.path.isdir(os.path.join(dest, "blutter", "src")):
        head = subprocess.run(["git", "-C", dest, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        if head == BLUTTER_COMMIT:
            print(f"[blutter] already at pinned commit {head}")
            return 0
        print(f"[blutter] existing checkout is {head}; re-pinning")
    os.makedirs(dest, exist_ok=True)
    if not os.path.isdir(os.path.join(dest, ".git")):
        run(["git", "-C", dest, "init", "-q"])
        run(["git", "-C", dest, "remote", "add", "origin", BLUTTER_REPO])
    else:
        subprocess.run(["git", "-C", dest, "remote", "set-url", "origin", BLUTTER_REPO], check=False)
    if not git_ok(["-C", dest, "fetch", "--depth", "1", "origin", BLUTTER_COMMIT]):
        raise SystemExit("[blutter] git fetch failed; check network/credentials")
    run(["git", "-C", dest, "checkout", "-f", "FETCH_HEAD"])
    print(f"[blutter] ready at {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
