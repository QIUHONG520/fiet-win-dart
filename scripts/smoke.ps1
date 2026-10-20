# fiet-win-dart smoke test (ASCII only; Windows PowerShell 5.1 compatible).
#
# 1) Verifies the DLL + runtime dependencies load (LoadLibrary) and exports
#    blutter_analyze / fler_engine_info.
# 2) With -Apk: extracts lib/arm64-v8a/libapp.so from an APK and runs real
#    analysis, then reports rc and SQLite row counts.
# 3) With -LibApp: runs analysis directly on an extracted libapp.so.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1 -EngineDir .\dist\dartvm-3.12.2-windows-x64
#   powershell -ExecutionPolicy Bypass -File .\scripts\smoke.ps1 -EngineDir .\dist\dartvm-3.13.5-windows-x64 -Apk .\samples\app.apk
param(
    [Parameter(Mandatory = $true)][string]$EngineDir,
    [string]$Apk = '',
    [string]$LibApp = '',
    [string]$OutDir = '',
    [switch]$LoadOnly,
    [switch]$KeepTemp
)
$ErrorActionPreference = 'Stop'

function Fail([string]$msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; exit 1 }
function Ok([string]$msg) { Write-Host "OK: $msg" -ForegroundColor Green }
function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

$engineDir = (Resolve-Path $EngineDir).Path
$dll = Get-ChildItem $engineDir -Filter 'dartvm_*_windows_x64.dll' | Select-Object -First 1
if (-not $dll) { Fail "no dartvm_*_windows_x64.dll in $engineDir" }
Step ("engine DLL: " + $dll.FullName + " (" + $dll.Length + " bytes)")

$pdb = [System.IO.Path]::GetDirectoryName($dll.FullName)
$env:PATH = $pdb + ';' + $env:PATH

# Dynamic P/Invoke so the script works for any Dart version in the file name.
$code = @"
using System;
using System.Runtime.InteropServices;
public static class FietWinDartSmoke {
    [DllImport("kernel32", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool SetDllDirectory(string path);
    [DllImport("$($dll.Name)", CallingConvention = CallingConvention.Cdecl)]
    public static extern int blutter_analyze(string soPath, string dbPath, string outDir);
    [DllImport("$($dll.Name)", CallingConvention = CallingConvention.Cdecl)]
    public static extern IntPtr fler_engine_info();
    [DllImport("kernel32", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr LoadLibraryW(string path);
}
"@
Add-Type -TypeDefinition $code
[void][FietWinDartSmoke]::SetDllDirectory($pdb)
$h = [FietWinDartSmoke]::LoadLibraryW($dll.FullName)
if ($h -eq [IntPtr]::Zero) { Fail ("LoadLibrary failed, Win32=" + [Runtime.InteropServices.Marshal]::GetLastWin32Error()) }
Ok "LoadLibrary"

$info = [Runtime.InteropServices.Marshal]::PtrToStringAnsi([FietWinDartSmoke]::fler_engine_info())
Ok ("fler_engine_info: " + $info)

$temp = if ($OutDir -ne '') { $OutDir } else { Join-Path ([System.IO.Path]::GetTempPath()) ('fiet-win-dart-smoke-' + [Guid]::NewGuid().ToString('N')) }
New-Item -ItemType Directory -Force -Path $temp | Out-Null
$sample = ''
if ($Apk -ne '') {
    Step "extracting lib/arm64-v8a/libapp.so from APK"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $Apk).Path)
    try {
        $entry = $zip.Entries | Where-Object { $_.FullName -eq 'lib/arm64-v8a/libapp.so' } | Select-Object -First 1
        if (-not $entry) { Fail "APK has no lib/arm64-v8a/libapp.so: $Apk" }
        $sample = Join-Path $temp 'libapp.so'
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $sample, $true)
    } finally { $zip.Dispose() }
} elseif ($LibApp -ne '') {
    $sample = (Resolve-Path $LibApp).Path
}
if ($LoadOnly) { Ok "load-only mode: skipping analysis"; exit 0 }
if ($sample -eq '') { Fail "either -Apk or -LibApp is required for analysis" }
$db = Join-Path $temp 'analysis.db'
$out = Join-Path $temp 'products'
New-Item -ItemType Directory -Force -Path $out | Out-Null
Step ("running blutter_analyze libapp=" + $sample)
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$rc = [FietWinDartSmoke]::blutter_analyze($sample, $db, $out)
$sw.Stop()
Write-Host ("    rc=" + $rc + " elapsed=" + [Math]::Round($sw.Elapsed.TotalSeconds, 1) + "s")
if ($rc -ne 0) { Fail "blutter_analyze rc=$rc (see stderr above)" }
if (-not (Test-Path $db)) { Fail "no SQLite database generated: $db" }
Ok ("database: " + $db + " (" + (Get-Item $db).Length + " bytes)")

$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    $counts = & $py.Source -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(' '.join('%s=%d'%(t,c.execute('select count(*) from '+t).fetchone()[0]) for t in ['classes','methods','strings'] if c.execute(\"select count(*) from sqlite_master where type='table' and name=?\",(t,)).fetchone()[0]))" $db
    Ok ("row counts: " + $counts)
}
if (-not $KeepTemp) { } else { Write-Host ("temp kept: " + $temp) }
Ok "smoke passed"
exit 0
