# Integration notes: loading the fiet-win-dart engine from FIET (Windows)

> v2.5 · 2026-10-20 · for the FIET-Windows integration task.
> This repository produces a **Windows x64 DLL** that analyzes Android arm64
> Flutter `libapp.so` AOT snapshots and writes a fler-dart-schema SQLite DB.
> Existing FIET-Windows code (`BlutterDbReader`, `blutter_*` tools) reads that
> schema unchanged; only engine discovery/download/load is new.

## 1. Package layout

Each engine package (`dartvm-<DartVersion>-windows-x64.zip` from Releases or CI)
extracts to a directory containing:

```
dartvm_<DartVersion>_windows_x64.dll   # engine, exports blutter_analyze / fler_engine_info
capstone.dll                            # runtime dependency (capstone 4.0.2, upstream blutter)
icuuc73.dll                             # runtime dependency (ICU 73.2)
icudt73.dll                             # runtime dependency (ICU 73.2)
SHA256SUMS.txt / LICENSE / NOTICE
```

Suggested install location for FIET-Windows (consistent with the existing
`enginesDir` naming convention `dartvm_*`):

```
%LOCALAPPDATA%\FIET-Windows\engines\windows-x64\dartvm_<DartVersion>_windows_x64\
    dartvm_<DartVersion>_windows_x64.dll
    capstone.dll
    icuuc73.dll
    icudt73.dll
```

(or flat in `%LOCALAPPDATA%\FIET-Windows\engines\` with `dartvm_*.dll` — the
directory just needs `SetDllDirectory`/altered search path for the deps).

## 2. C ABI

```c
// cdecl, UTF-8 char*
int blutter_analyze(const char* libapp_so_path,
                    const char* db_path,
                    const char* out_dir);

// engine metadata (Dart version / target / host / exports)
const char* fler_engine_info(void);
```

* `libapp_so_path` — extracted `lib/arm64-v8a/libapp.so` from a Flutter APK
  (Android arm64 only; that is the snapshot the engine is built to read).
* `db_path` — output SQLite path. Parent directory must exist/writable.
* `out_dir` — optional directory for extra products (`pp.txt`, `objs.txt`,
  `asm/`, `blutter_frida.js`). May be empty/null to skip.
* Return codes:
  * `0` — analysis finished (SQLite written; may be *partial* if CodeAnalyzer
    crashed and SEH fallback kicked in — check `analysis_meta`/row counts).
  * `-1` — temp dir creation failed (unlikely).
  * `-2` — analysis threw (bad/corrupt snapshot, wrong Dart version, OOM…).
  * `-3` — SQLite open failed (bad db path).
* The DLL is **not thread-safe across concurrent calls** (fler-dart reuses one
  Dart VM/isolate; Android serializes analyses). Call it from one dedicated
  thread, or better from a short-lived **child process**, so a hard crash cannot
  take down the MCP server.
* On Windows the CodeAnalyzer crash isolation uses SEH (`__try/__except`); the
  rest of the analysis then continues without disassembly (same degradation
  semantics as Android's sigaction path).

## 3. Loading from JVM/FIET (JNA)

```kotlin
interface FlerWinDart : Library {
    fun blutter_analyze(libAppSo: String, dbPath: String, outDir: String): Int
    fun fler_engine_info(): String?   // Pointer → String, see below
}
val lib = Native.load(dll.absolutePath, FlerWinDart::class.java) // JNA
```

Important: `Native.load(absolutePath, …)` uses `LoadLibraryEx` with an altered
search path for the *DLL itself*, but its dependencies (`capstone.dll`, ICU) are
searched on the standard search order. Safest options:

1. Before loading, call `SetDllDirectory(engineDir)` via JNA (`Kernel32`) — then
   `Native.load`; or
2. Ship the 4 DLLs in the **same directory as `java.exe`** (not desirable), or
3. Pre-load dependencies in order with `Native.load("capstone.dll")` etc. after
   `SetDllDirectory`.

A practical FIET-side layout: engine extracted to
`engines\windows-x64\<ver>\`; at startup `SetDllDirectory(that dir)` then
`System.load`/JNA-load the engine DLL.

## 4. Decision flow for FIET-Windows (suggested)

```
detect_dart_version libflutter.so
  -> manifest (windows-x64) has dartVersion?            [new]
       no  -> existing structured UNSUPPORTED_PLATFORM degradation (current behavior)
       yes -> engine package installed under engines\windows-x64\<ver>\?
                no -> download zip (manifest url + sha256), extract, verify SHA256
                yes-> SetDllDirectory(engineDir) + load DLL + probe fler_engine_info()
                        fail -> structured engine-not-loadable error (rc=-999 style), keep degradation
                        ok   -> run blutter_analyze on libapp.so (dedicated child process recommended)
                                 -> open resulting db with existing BlutterDbReader (no schema change)
```

Manifest shape (see `manifest.json`):

```json
{
  "schema": 1, "platform": "windows-x64", "targetAbi": "android-arm64",
  "engineApi": {"exports": ["blutter_analyze", "fler_engine_info"], "callingConvention": "cdecl"},
  "engines": [{
    "dartVersion": "3.12.2",
    "dll": "dartvm_3.12.2_windows_x64.dll",
    "file": "dartvm-3.12.2-windows-x64.zip",
    "url": "https://github.com/QIUHONG520/fiet-win-dart/releases/download/<tag>/dartvm-3.12.2-windows-x64.zip",
    "sha256": "…", "sizeBytes": 0,
    "runtimeDeps": ["capstone.dll", "icuuc73.dll", "icudt73.dll"]
  }]
}
```

## 5. What stays unchanged in FIET-Windows

* `core/analysis/BlutterDbReader.kt` — reads the same SQLite schema
  (`classes`, `methods`, `asm_blocks`, `pp_entries`, `strings`, `analysis_meta`, …).
* All `blutter_*` MCP tools and `blutter_*` analysis records.
* The degraded path (`UNSUPPORTED_PLATFORM` / `IMPORTED_DB`) remains as fallback
  for unsupported Dart versions / missing engine packages.

## 6. Testing checklist

- [ ] Engine DLL + deps extract; `smoke.ps1 -EngineDir <dir>` reports LoadLibrary OK,
      `fler_engine_info` OK, expected-error path for a missing libapp.
- [ ] Real APK whose `libflutter.so` Dart version matches the engine: analysis
      produces a DB with non-zero `classes`/`methods`.
- [ ] Wrong-Dart-version APK returns rc=-2 (no crash) and DB is absent/empty.
- [ ] Corrupted `libapp.so`: no crash of the host JVM (child process recommended).
- [ ] Engine not loadable (missing ICU/capstone): FIET returns structured error and
      keeps the existing degradation message.
