"""Run Python code inside a real Blender interpreter, from a normal test process.

Every check is executed in its own short-lived subprocess because a crash, a
segfault or a hang in one check must not take the rest of the suite down -- and
`bpy` as a module can hang during interpreter shutdown, so the child calls
os._exit() once its work is done.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

BPY_SHIM = os.environ.get("BPY_SHIM_DIR", os.path.expanduser("~/.bpyshim"))
BPY_PYTHON = os.environ.get("BPY_PYTHON", os.path.expanduser("~/.venv/bin/python"))

PROLOGUE = """
import json, os, sys, traceback

_results = []

def check(label, fn):
    try:
        value = fn()
    except Exception:
        _results.append({"label": label, "ok": False, "detail": traceback.format_exc()})
    else:
        _results.append({"label": label, "ok": True, "detail": value})

def finish():
    sys.stdout.write("\\n===RESULTS===\\n" + json.dumps(_results) + "\\n")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if all(r["ok"] for r in _results) else 1)
"""


class BlenderError(RuntimeError):
    """Raised when the Blender subprocess fails to run or reports no results."""


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["LD_PRELOAD"] = os.path.join(BPY_SHIM, "shim.so")
    env["LD_LIBRARY_PATH"] = (
        os.path.join(BPY_SHIM, "lib") + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    )
    return env


def run_in_blender(body: str, timeout: int = 300) -> list[dict]:
    """Execute `body` inside Blender and return the list of check results.

    `body` may use `check(label, fn)` and must not need to call `finish()`
    itself -- it is appended automatically.
    """
    if not os.path.exists(BPY_PYTHON):
        raise BlenderError(
            f"no Blender interpreter at {BPY_PYTHON}. Run tools/setup_bpy_env.sh first."
        )

    script = PROLOGUE + "\nimport bpy\n" + textwrap.dedent(body) + "\nfinish()\n"
    proc = subprocess.run(
        [BPY_PYTHON, "-c", script],
        capture_output=True, text=True, env=_env(), timeout=timeout,
    )

    marker = "===RESULTS===\n"
    if marker not in proc.stdout:
        raise BlenderError(
            f"blender subprocess exited {proc.returncode} with no results\n"
            f"--- stdout ---\n{proc.stdout[-3000:]}\n--- stderr ---\n{proc.stderr[-3000:]}"
        )
    payload = proc.stdout.split(marker, 1)[1].strip().splitlines()[0]
    return json.loads(payload)


def blender_version() -> str:
    results = run_in_blender("check('version', lambda: bpy.app.version_string)", timeout=120)
    return results[0]["detail"]


def assert_checks(results: list[dict]) -> None:
    """Turn a results list into an assertion failure naming the first problem."""
    failures = [r for r in results if not r["ok"]]
    if failures:
        text = "\n".join(f"- {r['label']}: {r['detail']}" for r in failures)
        raise AssertionError(f"{len(failures)} check(s) failed in Blender:\n{text}")


if __name__ == "__main__":  # tiny smoke entry: python tests/blender_runner.py
    print("blender:", blender_version(), file=sys.stderr)
