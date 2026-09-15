@echo off
REM Double-click launcher (Windows) for the Blender AI Dashboard.
REM This runs a local web app - it is NOT a browser extension.
cd /d %~dp0
where python >nul 2>nul
if %errorlevel% neq 0 (
  echo Python was not found. Install Python 3.10+ from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)
python dashboard\server.py --open %*
if %errorlevel% neq 0 pause
