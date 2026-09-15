#!/usr/bin/env bash
# Double-click launcher (macOS / Linux) for the Blender AI Dashboard.
# This RUNS a local web app - it is NOT installed, NOT a browser extension.
# It just starts a page on http://localhost:8899 - nothing is installed.
cd "$(dirname "$0")" || exit 1
if [ ! -f "dashboard/server.py" ]; then
  echo ""
  echo "  [Blender AI Dashboard] Cannot find dashboard/server.py next to this launcher."
  echo "  Download the FULL repository (GitHub: Code -> Download ZIP), extract it,"
  echo "  and run start-dashboard.sh from inside the extracted folder."
  echo ""
  read -r -p "Press Enter to close... " _
  exit 1
fi
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo ""
  echo "  [Blender AI Dashboard] Python was not found."
  echo "  Install Python 3.10+: macOS 'brew install python3' (or python.org);"
  echo "  Ubuntu/Debian 'sudo apt install python3'. Then run this again."
  echo ""
  read -r -p "Press Enter to close... " _
  exit 1
fi
exec "$PY" dashboard/server.py --open "$@"
