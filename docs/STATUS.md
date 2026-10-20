# Status — Windows Blutter engine (fiet-win-dart)

Last updated: 2026-10-20 (v2.5 task). This file is the precise state of the port.

## Validated engines (real end-to-end analysis on Windows x64)

| Dart version | Build | E2E analysis | Notes |
|---|---|---|---|
| **3.13.5** | ✅ `dartvm_3.13.5_windows_x64.dll` (8.67 MB) | ✅ **PASS** on FluffyChat 2.11.1 (Dart 3.13.5): rc=0 in **15.4 s** | Dart 3.13 "single snapshot" patches, see below |
| **3.12.2** | ✅ `dartvm_3.12.2_windows_x64.dll` (8.73 MB) | ⏳ load + invalid-input tested (rc=-2, no crash); needs a Dart-3.12.2 APK sample for full E2E | Baseline PoC |

E2E result for **FluffyChat 2.11.1 arm64 APK** (26.1 MB `libapp.so`, Dart 3.13.5):

```
RC=0 elapsed=15.4s
SQLite db size = 565,334,016 bytes
tables: analysis_meta, asm_blocks, call_edges, classes, enum_map,
        method_analysis, methods, objs, pp_entries, string_refs, strings
classes      = 10,715
methods      = 82,125
asm_blocks   = 75,049
pp_entries   = 81,212
strings      = 49,241
call_edges   = 290,949
analysis_meta: engine_abi=fler-dart-v0.5.33, dart_version=3.13.5, compressed_pointers=true
```

Products dumped: `pp.txt`, `objs.txt`, `asm/`, `ida_script`, `blutter_frida.js`.

## What builds

Windows x64 engine DLL from:

* Dart VM static lib built from official Dart SDK sources (host Windows x64,
  target android/arm64, `DART_PRECOMPILED_RUNTIME` + `DART_COMPRESSED_POINTERS`),
* pinned worawit/blutter `4a60ac6` analysis sources + robustness patches,
* fler-dart wrapper ported from POSIX to Win32 + SEH (`blutter_analyze`,
  `fler_engine_info`, SQLite export with fler-dart schema),
* SQLite amalgamation, capstone 4.0.2 + ICU 73.2 runtime DLLs.

Verified: `dumpbin /exports` → `blutter_analyze`, `fler_engine_info`.
`fler_engine_info()` reports the build-time Dart version (`dart=3.13.5` etc.).
Invalid `libapp.so` → `blutter_analyze` returns `-2` with
`ELF: Invalid magic header`, no crash.

## Dart 3.13 "single snapshot" support (new)

Dart 3.13 changed the AOT snapshot/VM layout; the pinned blutter revision did
not support it (upstream worawit/blutter issue #213 "Add Dart 3.13 single-snapshot
support" is still open). The following patches were written for this port and are
applied automatically by `scripts/prepare_blutter.py` (all gated by
`BLUTTER_DART_3_13_SINGLE_SNAPSHOT`; CMake defines it for Dart >= 3.13, so older
versions keep the original code paths):

1. **Snapshot symbols** (`ElfHelper.cpp`): `_kDartVmSnapshotData` /
   `_kDartVmSnapshotInstructions` / `_kDartIsolateSnapshot*` no longer exist;
   Dart 3.13 embeds one `_kDartSnapshotData` + `_kDartSnapshotText` pair.
   Patch maps VM/isolate pointers to that pair.
2. **`Dart_InitializeParams`** (`DartLoader.cpp`): `vm_snapshot_data` /
   `vm_snapshot_instructions` fields removed; the snapshot is passed to
   `Dart_CreateIsolateGroup` only.
3. **Stub lists** (`DartStub.h`, `DartApp.cpp`): `OBJECT_STORE_STUB_CODE_LIST`
   was removed. Dart 3.13 exposes all predefined stubs via `dart::StubCode`
   (`VM_STUB_CODE_LIST`), so `loadStubs()` iterates that list (stub kinds keep the
   historic `name##Stub` spelling used by CodeAnalyzer); `throw` comes from
   `StubCode::Throw()`.
4. **API/layout deltas**:
   * `AOT Closure` lost `context` / `delayed_type_arguments` fields → sentinel
     offsets make the two closure-prologue special cases inert (analysis continues);
   * `Code::operator=(const Code&)` deleted → assign `CodePtr` for the throw stub;
   * `FridaWriter`: closure `contextOffset` emitted as `-1`.
5. **Robustness/tolerance** (needed to survive 3.13 snapshots):
   * `DartTypes.cpp`: unknown abstract-type class ids map to `dynamic` instead of
     `FATAL()` abort;
   * robustness patch look-ahead bails use `FLER_SPLIT_CFG_BAIL` (throw
     `InsnException`), valid in both void and value-returning recognizers, and
     caught by per-function recovery;
   * optional-recognizer look-aheads no longer abort the whole analysis.

## Version gate — do not mix Dart versions

Feeding a **3.13.5** `libapp.so` to the **3.12.2** engine crashes the calling
process (AccessViolation inside Dart VM snapshot loading) because the VM tries to
deserialize an incompatible snapshot. This is inherent to the blutter approach
(one engine per Dart version). FIET must:

1. detect the Dart version from `libflutter.so` first (existing FIET
   `DartVersionDetector`), then load **only the matching engine package**;
2. run `blutter_analyze` in a **short-lived child process** so even a mismatch or
   corrupt input cannot take down the MCP server.

Documented in `docs/INTEGRATION.md`; `fler_engine_info()` allows a cheap
post-load version check.

## Artifacts

`dist/` (binaries ignored by git, released as GitHub Release assets):

| package | DLL | zip size | sha256 (zip) |
|---|---|---|---|
| `dartvm-3.12.2-windows-x64.zip` | `dartvm_3.12.2_windows_x64.dll` 8.73 MB | 16,443,835 B | `cc6859b57f880067163837a332b7c323e2403318344ccc8a9f0e1f60ea9105bf` |
| `dartvm-3.13.5-windows-x64.zip` | `dartvm_3.13.5_windows_x64.dll` 8.67 MB | 16,430,035 B | `a294fb5fcb9727085eef90fd3f9553502fd7c4fa675c95f8c35bc84d16db22fb` |

Both packages contain `capstone.dll`, `icuuc73.dll`, `icudt73.dll`,
`SHA256SUMS.txt`, `LICENSE`, `NOTICE`. `manifest.json` lists both engines with
Dart version / sha256 / size / download URL (release tag `v0.1.0-poc`).

## Pending / next steps

1. **Push + Release are blocked on GitHub write permission**: the provided PAT is a
   fine-grained token with only *Metadata: read* (`git push` → 403,
   `POST /releases` → 403, `PUT /contents` → 403). All changes are committed
   locally (commit SHA reported to the Lead). Needs a PAT with
   **Contents: Read and write** + **Workflows: Read and write** (repo
   `QIUHONG520/fiet-win-dart`), or a classic token with `repo`,`workflow`.
2. **CI matrix** (`.github/workflows/build-windows.yml`) has not run yet. It builds
   3.12.2 and 3.13.5 (validated locally, non-experimental) plus
   3.11.5/3.10.9/3.9.4/3.8.3/3.7.3/3.6.2/3.5.4 as `experimental`; older versions
   need their own MSVC/Dart patches validated.
3. Find a Flutter APK built with Dart **3.12.2** to run the full E2E on that engine
   (3.13.5 already PASS; 3.12.2 load/invalid-input PASS).
4. Optional hardening: export `fler_engine_dart_version()` for a pre-analysis
   gate, and/or detect the snapshot version from `libapp.so` before creating the
   Dart VM.
5. FIET-Windows integration (manifest-driven engine download → install under
   `engines\windows-x64\<version>\` → `SetDllDirectory` + JNA load → child-process
   analysis) — see `docs/INTEGRATION.md`.

## Build commands (reproducible)

```powershell
# one-shot: blutter + Dart SDK 3.13.5 + deps, build VM + DLL, package
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -DartVersion 3.13.5

# just the DLL (after a previous full build)
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -DartVersion 3.13.5 -SkipDartVM

# smoke (load + exports + expected invalid-input failure)
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1 -EngineDir .\dist\dartvm-3.13.5-windows-x64

# real analysis (Dart version must match the engine; sample APK required)
powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1 `
  -EngineDir .\dist\dartvm-3.13.5-windows-x64 -Apk .\samples\app.apk
```

## Environment notes

- Visual Studio 2022 Build Tools 17.14.42 (MSVC 14.44.35207), CMake 3.31.6,
  Ninja, Python 3.11, Windows 11.
- Dart SDK sources are fetched from the GitHub codeload tarball (36–37 MiB
  compressed, ~400 MB extracted) instead of `git clone`, because plain git
  connections to GitHub were rate-limited in this environment.
- Upstream blutter pinned to `4a60ac648bf448c5a7596437243bcd0b9376fdf0` (this
  commit already contains the `fix/dart311-leaf-runtime-ldur` merge).
- ICU/capstone Windows binaries come from upstream blutter's
  `scripts/init_env_windows.py` (ICU 73.2, capstone 4.0.2).
