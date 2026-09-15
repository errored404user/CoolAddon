#!/usr/bin/env bash
# Double-click launcher (macOS / Linux) for the Blender AI Dashboard.
# This runs a local web app - it is NOT a browser extension.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 dashboard/server.py --open "$@"
else
  python dashboard/server.py --open "$@"
fi
