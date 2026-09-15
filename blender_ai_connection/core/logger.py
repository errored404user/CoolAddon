"""Central logging for the Blender AI Connection addon.

- Always keeps an in-memory ring buffer (works without Blender).
- Prints to stdout (visible in Blender's system console).
- Mirrors into Scene property collection when running on Blender's main thread,
  so the N-panel log list stays in sync.
"""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}

_level = "INFO"
_buffer: Deque[Dict[str, str]] = deque(maxlen=500)


def set_level(level: str) -> None:
    global _level
    level = (level or "INFO").upper()
    _level = level if level in LEVELS else "INFO"


def get_level() -> str:
    return _level


def clear() -> None:
    _buffer.clear()
    _mirror_clear()


def _should_emit(level: str) -> bool:
    return LEVELS.get(level, 20) >= LEVELS.get(_level, 20)


def log(level: str, message: str) -> None:
    level = (level or "INFO").upper()
    if level not in LEVELS:
        level = "INFO"
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "message": str(message)[:2000],
    }
    _buffer.append(entry)
    if _should_emit(level):
        print(f"[BlenderAI:{level}] {entry['message']}")
    _mirror_append(entry)


def debug(msg: str) -> None:
    log("DEBUG", msg)


def info(msg: str) -> None:
    log("INFO", msg)


def warning(msg: str) -> None:
    log("WARNING", msg)


def error(msg: str) -> None:
    log("ERROR", msg)


def get_recent(count: int = 100, min_level: str = "DEBUG") -> List[Dict[str, str]]:
    threshold = LEVELS.get(min_level.upper(), 0)
    items = [e for e in _buffer if LEVELS.get(e["level"], 0) >= threshold]
    return items[-max(1, count):]


# ---------------------------------------------------------------------------
# Blender property mirror (main thread only — never touch bpy off main thread)
# ---------------------------------------------------------------------------

def _on_main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()


def _mirror_append(entry: Dict[str, str]) -> None:
    if not _on_main_thread():
        return
    try:
        import bpy  # type: ignore

        for scene in getattr(bpy.data, "scenes", []):
            props = getattr(scene, "blender_ai", None)
            if props is None:
                continue
            try:
                limit = 300
                try:
                    limit = int(getattr(props, "log_limit", 300))
                except (TypeError, ValueError):
                    pass
                item = props.logs.add()
                item.level = entry["level"]
                item.time = entry["time"]
                item.message = entry["message"][:1000]
                while len(props.logs) > max(20, limit):
                    props.logs.remove(0)
            except (AttributeError, RuntimeError, TypeError):
                continue
    except ImportError:
        pass
    except (AttributeError, RuntimeError):
        pass


def _mirror_clear() -> None:
    if not _on_main_thread():
        return
    try:
        import bpy  # type: ignore

        for scene in getattr(bpy.data, "scenes", []):
            props = getattr(scene, "blender_ai", None)
            if props is not None:
                try:
                    props.logs.clear()
                except (AttributeError, RuntimeError, TypeError):
                    pass
    except ImportError:
        pass
    except (AttributeError, RuntimeError):
        pass
