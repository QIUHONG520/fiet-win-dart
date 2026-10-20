# dist/

Engine packages produced by `scripts/build.ps1` (Dart VM static lib + engine DLL
+ runtime dependencies). Binary files (`.dll`, `.zip`) are **not committed** to
this repository; the validated PoC package is attached to the GitHub release
`v0.1.0-poc` and referenced by `manifest.json`:

* `dartvm-3.12.2-windows-x64.zip`
  * `dartvm_3.12.2_windows_x64.dll` — engine (exports `blutter_analyze`, `fler_engine_info`)
  * `capstone.dll`, `icuuc73.dll`, `icudt73.dll` — runtime dependencies
  * `SHA256SUMS.txt`, `LICENSE`, `NOTICE`

Download + verify:

```powershell
curl.exe -L -o dartvm-3.12.2-windows-x64.zip `
  https://github.com/QIUHONG520/fiet-win-dart/releases/download/v0.1.0-poc/dartvm-3.12.2-windows-x64.zip
# compare with manifest.json -> engines[0].sha256
```

After extraction keep the four DLLs in the same directory (see
`docs/INTEGRATION.md` for loading from FIET/JNA).
