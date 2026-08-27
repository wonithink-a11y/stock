@echo off
chcp 65001 >nul
setlocal

rem This file is intentionally ASCII-only. Mixing Korean text into a .bat
rem line can get misread by cmd.exe's own line parser depending on the
rem active codepage at the moment each line is read, which splits one
rem echo command into several bogus "commands" (this happened once,
rem 2026-08-27 - fixed by moving all Korean prompts into the Python
rem script, which handles its own encoding).

where python >nul 2>nul
if not errorlevel 1 goto :run

rem Explorer-launched processes can inherit a stale PATH that predates a
rem Python install/PATH update (a known Windows quirk - the registry PATH
rem is correct but already-running explorer.exe does not re-read it until
rem restart/logoff). Fall back to the known install location directly.
set "FALLBACK=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if exist "%FALLBACK%" (
    set "PY_EXE=%FALLBACK%"
    goto :run
)

echo Could not find python.exe.
echo Open a terminal yourself and run:
echo   python "%~dp0scripts\setup-keys-interactive.py"
pause
exit /b 1

:run
if not defined PY_EXE set "PY_EXE=python"
"%PY_EXE%" "%~dp0scripts\setup-keys-interactive.py"
