#!/bin/sh
# One-time setup of a real, headless Blender used to test this addon.
#
# Installs Blender's official `bpy` pip module (the genuine CPython build of
# Blender, not a mock) and builds the X11/GL shim that lets it load on a slim
# container. Everything lands outside the repo, so nothing binary is committed.
#
#   BPY_VERSION  Blender series to install   (default 4.5.0)
#   VENV         where to create the venv    (default ~/.venv)
#   BPY_SHIM_DIR where to build the shim     (default ~/.bpyshim)
set -eu

BPY_VERSION="${BPY_VERSION:-4.5.0}"
VENV="${VENV:-$HOME/.venv}"
BPY_SHIM_DIR="${BPY_SHIM_DIR:-$HOME/.bpyshim}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# bpy 4.5 wheels are built for CPython 3.11.
PY_MINOR="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$PY_MINOR" != "3.11" ]; then
    echo "warning: bpy ${BPY_VERSION} needs Python 3.11, this is ${PY_MINOR}" >&2
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "==> creating venv at $VENV"
    python3 -m venv "$VENV"
fi

echo "==> installing bpy==${BPY_VERSION} (a ~370 MB wheel)"
"$VENV/bin/pip" install --no-cache-dir --quiet "bpy==${BPY_VERSION}" pytest

echo "==> building the X11/GL shim in $BPY_SHIM_DIR"
python3 "$REPO_ROOT/tools/build_bpy_shim.py" "$BPY_SHIM_DIR" --python "$VENV/bin/python"

echo
echo "done. run the suite with:"
echo "  BPY_PYTHON=$VENV/bin/python $VENV/bin/python -m pytest tests -q"
