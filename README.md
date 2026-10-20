# fiet-win-dart

Windows x64 Blutter / Dart-VM engine for **FIET** — on-device quality Flutter AOT
analysis for the Windows desktop app.

This repository builds a self-contained Windows x64 DLL that exports a single C ABI:

```c
// analyze an Android arm64 Flutter `libapp.so`, write results to SQLite
int  blutter_analyze(const char* libapp_so_path, const char* db_path, const char* out_dir);
// engine metadata: dart version / target / host / exported functions
const char* fler_engine_info(void);
```

It is the Windows port of
[QIUHONG520/fler-dart](https://github.com/QIUHONG520/fler-dart) (the Android arm64
Blutter engine used by FIET for Android), which itself is built on
[worawit/blutter](https://github.com/worawit/blutter). The upstream blutter
project supports Windows (MSVC + Visual Studio), so the Windows engine is built
with:

* Dart VM static library compiled for **Windows x64 host / Android arm64 target**
  (same `DART_PRECOMPILED_RUNTIME`/`TARGET_ARCH_ARM64` layout trick blutter uses),
* blutter analysis sources compiled into the DLL,
* the fler-dart wrapper (`blutter_analyze`) ported from POSIX to Win32 + SEH,
* SQLite amalgamation for the result database (schema matches fler-dart, so
  FIET's `BlutterDbReader` can read it unchanged).

> Status: **proof of concept** — one Dart version (3.12.2) builds and produces a
> DLL; the CI matrix and multi-version packaging are in progress. See
> [`docs/STATUS.md`](docs/STATUS.md) for the exact current state and next steps.

## Repository layout

```
cmake/CMakeLists.txt        # engine DLL build (MSVC, exports blutter_analyze)
wrapper/                    # Windows port of fler-dart's wrapper
  blutter_entry_win.cpp       #   blutter_analyze(): in-memory export -> SQLite
  seh_guard_win.cpp           #   SEH crash isolation for CodeAnalyzer (replaces sigaction)
  regexp_stubs.cpp            #   (POSIX/Android only; not used on Windows, kept for reference)
patches/patch-blutter-robust.py  # robustness + Dart version compat patches (from fler-dart)
scripts/
  build.ps1                 # one-shot build: blutter + Dart VM + DLL + package
  build-dartvm.cmd          # VS dev shell wrapper: build Dart VM static lib
  build-engine.cmd          # VS dev shell wrapper: build the engine DLL
  prepare_blutter.py        # clone/patch the pinned blutter tree
  prepare_dartsdk.py        # Dart SDK tree prep + MSVC compatibility patches
  fetch_dartsdk.py          # download Dart SDK source tarball (codeload, no git)
  fetch_sqlite.py           # download sqlite3 amalgamation
  make_manifest.py          # build manifest.json from dist/*
  smoke.ps1                 # LoadLibrary + blutter_analyze smoke test
.github/workflows/build-windows.yml  # windows-latest matrix build
third_party/sqlite/         # sqlite3.c (downloaded by build.ps1, not committed)
dist/                       # engine packages (DLL + runtime deps + zip), CI artifacts
```

## Build

Requirements (same as upstream blutter on Windows):

* Windows 10/11 x64
* Visual Studio 2022 Build Tools with **Desktop development with C++**
  (MSVC v143, CMake + Ninja components)
* Python 3.10+
* Git (for fetching the pinned blutter commit; the Dart SDK source itself is
  downloaded as a tarball so a slow/unreliable GitHub git connection is not a
  hard blocker)

```powershell
# from the repository root
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -DartVersion 3.12.2
```

The first run downloads:

* `worawit/blutter` @ `4a60ac648bf448c5a7596437243bcd0b9376fdf0` (pinned, patched),
* Dart SDK source for the requested version (codeload tarball),
* SQLite amalgamation,
* upstream blutter's Windows third-party deps (ICU 73.2 + capstone 4.0.2, via
  `blutter/scripts/init_env_win.py`).

Then it builds the Dart VM static library and the engine DLL, and writes
`dist/dartvm-<version>-windows-x64/`:

```
dartvm_<version>_windows_x64.dll   # exports blutter_analyze / fler_engine_info
capstone.dll                       # runtime dependency (upstream capstone 4.0.2)
icuuc73.dll / icudt73.dll          # runtime dependencies (ICU 73.2)
SHA256SUMS.txt
```

### Loading the DLL from FIET

The DLL depends on `capstone.dll`, `icuuc73.dll`, `icudt73.dll` in the same
directory. Load the DLL with an absolute path and an altered search path, or call
`SetDllDirectory(<engine-dir>)` first (FIET uses JNA `Native.load` on the absolute
DLL path; see the integration notes in `docs/STATUS.md`).

## Testing

```powershell
# quick load + export check + expected-error path (no Flutter sample needed)
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1 `
  -EngineDir .\dist\dartvm-3.12.2-windows-x64

# full analysis on a Flutter arm64 APK (Dart version must match the engine)
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1 `
  -EngineDir .\dist\dartvm-3.13.5-windows-x64 `
  -Apk .\samples\app.apk
```

Output is a fler-dart-schema SQLite database (`classes`, `methods`, `asm_blocks`,
`pp_entries`, `strings`, `analysis_meta`, `method_analysis`, ...) plus
`pp.txt`/`objs.txt`/`asm/` products in `out_dir`.

## License and third-party notices

The build scripts and Windows port in this repository are provided under the MIT
license (see `LICENSE`). The engine binary links/copies third-party components
with their own licenses — see `NOTICE` and keep the notices when redistributing:

* blutter — MIT (Copyright worawit)
* fler-dart wrapper — distributed here with the permission of the FIET project
  owner; no separate license is declared upstream (see NOTICE)
* Dart SDK / Dart VM — BSD-3-Clause (Google)
* Capstone — BSD-3-Clause
* ICU — Unicode License
* SQLite — Public Domain
