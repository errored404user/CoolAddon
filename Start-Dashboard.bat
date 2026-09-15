@echo off
REM Double-click launcher (Windows) for the Blender AI Dashboard.
REM This RUNS a local web app - it is NOT installed, NOT a browser extension.
REM It just starts a page on http://localhost:8899 - nothing is installed.
cd /d %~dp0
if not exist "dashboard\server.py" (
  echo.
  echo  [Blender AI Dashboard] Cannot find "dashboard\server.py" next to this launcher.
  echo  Download the FULL repository (GitHub: Code -^> Download ZIP), extract it,
  echo  and double-click Start-Dashboard.bat from inside the extracted folder.
  echo.
  pause
  exit /b 1
)
set PY=
where py >nul 2>nul
if %errorlevel% equ 0 set PY=py -3
where python >nul 2>nul
if %errorlevel% equ 0 if not defined PY set PY=python
if not defined PY (
  echo.
  echo  [Blender AI Dashboard] Python was not found on your system.
  echo  Opening the Python download page - install Python 3.10 or newer and
  echo  tick "Add python.exe to PATH" during setup. Then double-click this again.
  echo.
  start "" "https://www.python.org/downloads/"
  pause
  exit /b 1
)
%PY% "dashboard\server.py" --open %*
if %errorlevel% neq 0 (
  echo.
  echo  [Blender AI Dashboard] The dashboard stopped - see the error above^.
  echo  Common cause: the port is busy. Retry with: Start-Dashboard.bat --port 8900
  pause
)
