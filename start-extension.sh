#!/usr/bin/env bash
# Double-click launcher (macOS / Linux) for the Blender AI Extension dashboard.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 extension/server.py --open "$@"
else
  python extension/server.py --open "$@"
fi
