# Status — Windows Blutter engine (fiet-win-dart)

Last updated: 2026-10-20 (v2.5 task). This file is the precise state of the
port; update it as work progresses.

## Done

- **Repository skeleton**: CMake DLL build, Windows port of the fler-dart wrapper,
  blutter/Dart SDK fetch + patch pipeline, `build.ps1`, manifest generator,
  smoke test, GitHub Actions matrix workflow.
- **Dart 3.12.2 engine DLL builds on Windows x64 (MSVC 14.44 / VS2022 Build Tools)**:
  - Dart VM static lib (`dartvm3.12.2_android_arm64.lib`, 25.9 MB) built from
    official Dart SDK 3.12.2 sources — host Windows x64, target android/arm64,
    `DART_PRECOMPILED_RUNTIME` + `DART_COMPRESSED_POINTERS` (blutter layout trick).
  - `dartvm_3.12.2_windows_x64.dll` (8.7 MB) links blutter analysis sources +
    SQLite amalgamation. Exports verified with `dumpbin /exports`:
    `blutter_analyze`, `fler_engine_info`.
  - Runtime dependencies copied next to it: `capstone.dll` (5.6 MB),
    `icuuc73.dll` (2.3 MB), `icudt73.dll` (32 MB).
- **Runtime load test** (PowerShell `LoadLibrary` + P/Invoke):
  - `LoadLibrary` OK, `fler_engine_info()` returns
    `fiet-win-dart 0.1.0; dart=3.12.2; target=android_arm64; host=windows_x64; …`.
  - invalid `libapp.so` → graceful `rc=-2` with `ELF: Invalid magic header`
    (no crash, C++ exception path works).
- **MSVC compatibility patches for the Dart VM build** (documented in
  `scripts/prepare_dartsdk.py`, needed for older Dart versions):
  - Dart ≤3.11 `assert.h`/`log.h`/`debugger.h`/`isolate_reload.h`/`object.cc`
    `_MSC_VER` variadic macros → C++20 `__VA_OPT__` (otherwise `UNREACHABLE()`
    / `THR_Print("x")` expand to `Fail(fmt, )` → C2059 with `/Zc:preprocessor`).
  - `/Zc:preprocessor /utf-8` added to the Dart VM CMake template for MSVC.
  - `unwinding_records.h` RUNTIME_FUNCTION patch (blutter's own win32 workaround)
    applied only when the guarded form is present (Dart 3.13.5 currently).

## Known issues / next steps

1. **Real end-to-end analysis test is still pending a matching Flutter sample.**
   The engine analyzes Android arm64 AOT snapshots **of its own Dart version**;
   pairing it with a different Dart version is unsupported (same as Android).
   Local samples available in this workspace:
   - LocalSend 1.18.2 APK → Dart **3.11.5**,
   - FluffyChat 2.11.1 APK → Dart **3.13.5**.
   A real analysis test needs a Flutter APK built with Dart **3.12.2** (or a
   locally built engine for 3.11.5 / 3.13.5 — see issues 2/3).
   **Observed**: feeding a Dart 3.13.5 `libapp.so` to the 3.12.2 engine causes an
   AccessViolation inside Dart VM snapshot loading. There is currently only an
   SEH guard around CodeAnalyzer, so this crashes the calling process — this is
   exactly why FIET must (a) select the engine by detected Dart version and
   (b) run `blutter_analyze` in a **short-lived child process**. A version gate
   exported from the engine (`fler_engine_dart_version()`) is also worth adding.
2. **Dart 3.13.5 engine build currently fails** while compiling blutter sources:
   MSVC 19.44 reports `__msvc_ranges_tuple_formatter.hpp` /
   `DartApp.h(75) C2059` (std::format related when including Dart 3.13 headers).
   Needs investigation (probably a Dart 3.13 header/MSVC `<format>` interaction or
   an extra compat define). Dart 3.13.5 **Dart VM static lib builds fine**.
3. **Dart 3.11.5 VM build**: generic `, __VA_ARGS__)` → `__VA_OPT__` patch is now
   in `prepare_dartsdk.py`; rebuild and continue patching until green
   (previous failure was object.cc macros; latest script covers all runtime/
   files, needs re-run).
4. **GitHub Actions matrix has not been run yet** (workflow defined with 8 Dart
   versions; non-3.12.2 entries are `experimental` until validated locally/CI).
5. **FIET-Windows integration not done** (out of this repo): see
   `docs/INTEGRATION.md` for the suggested manifest/download/layout/JNA loading
   flow and the child-process isolation requirement.
6. **Release asset**: `dartvm-3.12.2-windows-x64.zip` (DLL + deps + SHA256SUMS +
   NOTICE/LICENSE) is attached to the `v0.1.0-poc` GitHub release; FIET should
   verify the SHA-256 from `manifest.json` after download.

## Build commands (reproducible)

```powershell
# one-shot: fetch blutter + Dart SDK 3.12.2 + deps, build VM + DLL, package
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -DartVersion 3.12.2

# just the DLL (after a previous full build)
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -DartVersion 3.12.2 -SkipDartVM

# smoke (load + exports + invalid input)
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1 -EngineDir .\dist\dartvm-3.12.2-windows-x64

# real analysis (Dart version must match the engine; sample APK required)
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1 `
  -EngineDir .\dist\dartvm-3.12.2-windows-x64 -Apk .\samples\flutter-app-dart-3.12.2.apk
```

## Environment notes

- This build was produced with Visual Studio 2022 **Build Tools** 17.14.42
  (MSVC 14.44.35207), CMake 3.31.6, Ninja, Python 3.11 on Windows 11.
- Dart SDK sources are fetched from the GitHub codeload tarball
  (`36–37 MiB` compressed, ~400 MB extracted) instead of `git clone`, because
  plain git connections to GitHub were rate-limited in the build environment.
- The upstream blutter tree is pinned to
  `4a60ac648bf448c5a7596437243bcd0b9376fdf0` (the commit fler-dart validated).
- ICU/capstone Windows binaries come from upstream blutter's
  `scripts/init_env_win.py` (ICU 73.2, capstone 4.0.2).
