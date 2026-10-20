@echo off
rem Build the Dart VM static library for one Dart version (Windows x64 host /
rem Android arm64 target, the layout blutter uses to read Flutter AOT snapshots).
rem
rem Usage: build-dartvm.cmd <dart-version>
rem Requires: VS2022 Build Tools (env FIET_VS_BUILD_TOOLS) + Python + Git on PATH.
setlocal
if "%~1"=="" (echo usage: build-dartvm.cmd ^<dart-version^> & exit /b 2)
set "VER=%~1"
set "ROOT=%~dp0.."
if "%FIET_VS_BUILD_TOOLS%"=="" set "FIET_VS_BUILD_TOOLS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
echo [vm] start version=%VER% root=%ROOT% %DATE% %TIME%
rem NOTE: do not put the PATH update in a parenthesised block below the vcvars
rem call: %PATH% would be expanded before vcvars adds the compiler to PATH.
if exist "%FIET_VS_BUILD_TOOLS%\VC\Auxiliary\Build\vcvars64.bat" call "%FIET_VS_BUILD_TOOLS%\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 (echo [vm] vcvars64 FAILED & exit /b 1)
where cl.exe >nul 2>nul || (echo [vm] no MSVC toolchain found; run from a VS developer prompt & exit /b 1)
set "PATH=%FIET_VS_BUILD_TOOLS%\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;%FIET_VS_BUILD_TOOLS%\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%"
cd /d "%ROOT%\src\blutter"
python dartvm_fetch_build.py %VER% android arm64
set RC=%ERRORLEVEL%
echo [vm] exit=%RC% version=%VER% %DATE% %TIME%
exit /b %RC%
