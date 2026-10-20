@echo off
rem Build the Windows x64 engine DLL for one Dart version.
rem Usage: build-engine.cmd <dart-version>
setlocal
if "%~1"=="" (echo usage: build-engine.cmd ^<dart-version^> & exit /b 2)
set "VER=%~1"
set "ROOT=%~dp0.."
if "%FIET_VS_BUILD_TOOLS%"=="" set "FIET_VS_BUILD_TOOLS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
echo [engine] start version=%VER% root=%ROOT% %DATE% %TIME%
rem NOTE: keep the PATH update outside any parenthesised block (see build-dartvm.cmd).
if exist "%FIET_VS_BUILD_TOOLS%\VC\Auxiliary\Build\vcvars64.bat" call "%FIET_VS_BUILD_TOOLS%\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 (echo [engine] vcvars64 FAILED & exit /b 1)
where cl.exe >nul 2>nul || (echo [engine] no MSVC toolchain found; run from a VS developer prompt & exit /b 1)
set "PATH=%FIET_VS_BUILD_TOOLS%\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin;%FIET_VS_BUILD_TOOLS%\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%"
cd /d "%ROOT%"
cmake -GNinja -S cmake -B "build\engine-%VER%" -DCMAKE_BUILD_TYPE=Release -DBLUTTER_DIR="%ROOT%\src\blutter" -DDART_VERSION="%VER%"
if errorlevel 1 (echo [engine] cmake configure FAILED & exit /b 1)
cmake --build "build\engine-%VER%"
if errorlevel 1 (echo [engine] build FAILED & exit /b 1)
echo [engine] output:
dir /b "build\engine-%VER%\*.dll"
dumpbin /exports "build\engine-%VER%\dartvm_%VER%_windows_x64.dll" | findstr /i "blutter_analyze fler_"
echo [engine] done version=%VER% %DATE% %TIME%
exit /b 0
