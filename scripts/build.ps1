# fiet-win-dart one-shot build (ASCII only; Windows PowerShell 5.1 / PowerShell 7).
#
# Steps:
#   1. fetch pinned worawit/blutter + apply fler-dart / Windows patches
#   2. fetch blutter's Windows third-party deps (ICU 73.2, capstone 4.0.2)
#   3. fetch SQLite amalgamation
#   4. fetch + prepare Dart SDK source for the requested version
#   5. build Dart VM static library (VS2022 dev shell wrapper .cmd)
#   6. build the engine DLL + copy runtime deps
#   7. package dist/dartvm-<version>-windows-x64/ + .zip + SHA256SUMS
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -DartVersion 3.12.2
param(
    [string]$DartVersion = '3.12.2',
    [string]$BlutterDir = '',
    [switch]$SkipDartVM,
    [switch]$NoPackage
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Python) { throw 'python not found on PATH (Python 3.10+ required)' }
function Step([string]$m) { Write-Host ('==> ' + $m) -ForegroundColor Cyan }
function Fail([string]$m) { Write-Host ('FAIL: ' + $m) -ForegroundColor Red; exit 1 }

# Locate VS 2022 Build Tools / VS (vcvars64.bat); allow explicit override via env.
if (-not $env:FIET_VS_BUILD_TOOLS) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path $vswhere) {
        $vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null
        if ($vs) { $env:FIET_VS_BUILD_TOOLS = $vs.Trim() }
    }
}
if (-not $env:FIET_VS_BUILD_TOOLS -or -not (Test-Path (Join-Path $env:FIET_VS_BUILD_TOOLS 'VC\Auxiliary\Build\vcvars64.bat'))) {
    Fail 'VS2022 C++ toolchain not found; install "Desktop development with C++" or set FIET_VS_BUILD_TOOLS to the VS installation dir'
}
Step ('VS2022: ' + $env:FIET_VS_BUILD_TOOLS)

if ($BlutterDir -eq '') { $BlutterDir = Join-Path $Root 'src\blutter' }
if (-not (Test-Path (Join-Path $BlutterDir 'blutter\src'))) {
    Step 'fetch pinned blutter'
    & $Python.Source (Join-Path $Root 'scripts\fetch_blutter.py') $BlutterDir
    if ($LASTEXITCODE -ne 0) { Fail 'fetch_blutter.py failed' }
}
Step 'patch blutter for Windows / fler-dart accessors'
& $Python.Source (Join-Path $Root 'scripts\prepare_blutter.py') $BlutterDir
if ($LASTEXITCODE -ne 0) { Fail 'prepare_blutter.py failed' }

$external = Join-Path $BlutterDir 'external'
if (-not (Test-Path (Join-Path $external 'icu-windows\lib64\icuuc.lib')) -or
    -not (Test-Path (Join-Path $external 'capstone\capstone.lib'))) {
    Step 'fetch blutter Windows third-party deps (ICU + capstone)'
    Push-Location (Join-Path $BlutterDir 'scripts')
    try {
        & $Python.Source 'init_env_win.py'
        if ($LASTEXITCODE -ne 0) { Fail 'init_env_win.py failed' }
    } finally { Pop-Location }
}

Step 'fetch sqlite amalgamation'
& $Python.Source (Join-Path $Root 'scripts\fetch_sqlite.py') (Join-Path $Root 'third_party\sqlite')
if ($LASTEXITCODE -ne 0) { Fail 'fetch_sqlite.py failed' }

$dartSrc = Join-Path $BlutterDir ('dartsdk\v' + $DartVersion)
if (-not (Test-Path (Join-Path $dartSrc 'runtime\vm\version_in.cc'))) {
    Step ('fetch Dart SDK source ' + $DartVersion)
    & $Python.Source (Join-Path $Root 'scripts\fetch_dartsdk.py') $DartVersion $dartSrc
    if ($LASTEXITCODE -ne 0) { Fail 'fetch_dartsdk.py failed' }
}
Step ('prepare Dart SDK source ' + $DartVersion)
& $Python.Source (Join-Path $Root 'scripts\prepare_dartsdk.py') $dartSrc '--version' $DartVersion
if ($LASTEXITCODE -ne 0) { Fail 'prepare_dartsdk.py failed' }

if (-not $SkipDartVM) {
    $vmLib = Join-Path $BlutterDir ('packages\lib\dartvm' + $DartVersion + '_android_arm64.lib')
    if (-not (Test-Path $vmLib)) {
        Step ('build Dart VM static lib ' + $DartVersion)
        & cmd.exe /c ('"' + (Join-Path $Root 'scripts\build-dartvm.cmd') + '" ' + $DartVersion)
        if ($LASTEXITCODE -ne 0) { Fail ('Dart VM build failed for ' + $DartVersion) }
    } else {
        Step ('Dart VM static lib already built: ' + $vmLib)
    }
}

Step ('build engine DLL ' + $DartVersion)
& cmd.exe /c ('"' + (Join-Path $Root 'scripts\build-engine.cmd') + '" ' + $DartVersion)
if ($LASTEXITCODE -ne 0) { Fail ('engine build failed for ' + $DartVersion) }

if ($NoPackage) { Step 'skip packaging (-NoPackage)'; exit 0 }

Step 'package dist/dartvm-' 
$engineDir = Join-Path $Root ('build\engine-' + $DartVersion)
$dll = Get-ChildItem $engineDir -Filter ('dartvm_' + $DartVersion + '_windows_x64.dll') -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dll) { Fail ('DLL not found in ' + $engineDir) }
$pkg = Join-Path $Root ('dist\dartvm-' + $DartVersion + '-windows-x64')
New-Item -ItemType Directory -Force -Path $pkg | Out-Null
Copy-Item $dll.FullName (Join-Path $pkg $dll.Name) -Force
foreach ($dep in @('capstone.dll', 'icuuc73.dll', 'icudt73.dll')) {
    $src = Join-Path $engineDir $dep
    if (Test-Path $src) { Copy-Item $src (Join-Path $pkg $dep) -Force }
}
Copy-Item (Join-Path $Root 'NOTICE') (Join-Path $pkg 'NOTICE') -Force
Copy-Item (Join-Path $Root 'LICENSE') (Join-Path $pkg 'LICENSE') -Force
$hashes = Get-ChildItem $pkg -Filter '*.dll' | ForEach-Object {
    $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    ($h + '  ' + $_.Name)
}
Set-Content -Path (Join-Path $pkg 'SHA256SUMS.txt') -Value $hashes -Encoding ASCII
$zip = Join-Path $Root ('dist\dartvm-' + $DartVersion + '-windows-x64.zip')
if (Test-Path $zip) { Remove-Item $zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($pkg, $zip)
$zipSha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
Set-Content -Path ($zip + '.sha256') -Value ($zipSha + '  ' + (Split-Path $zip -Leaf)) -Encoding ASCII
Write-Host ('    package: ' + $zip + ' (' + (Get-Item $zip).Length + ' bytes, sha256=' + $zipSha + ')') -ForegroundColor Green
Step 'done'
