"""Routes validated tool calls to their implementations.

Runs exclusively on Blender's main thread (called from the socket server's
timer callback or directly by UI operators). Never raises — every failure is
converted into a structured protocol error response.
"""

from __future__ import annotations

import time
import traceback
from typing import Any, Dict, Set

from . import logger
from .protocol import SYSTEM_TOOLS, make_error, make_response


_denied_override: Set[str] = set()


def set_denied_override(tool_ids) -> None:
    """Programmatic deny-list (used by tests / MCP server config)."""
    global _denied_override
    _denied_override = set(tool_ids or [])


def current_denied() -> Set[str]:
    """Combined deny-list (override + Blender preferences)."""
    return set(_denied_override) | _denied_from_prefs()


def _denied_from_prefs() -> Set[str]:
    try:
        import bpy  # type: ignore

        prefs = bpy.context.preferences.addons.get("blender_ai_connection")
        if prefs and hasattr(prefs, "preferences"):
            raw = getattr(prefs.preferences, "denied_tools", "") or ""
            return {t.strip() for t in raw.split(",") if t.strip()}
    except (AttributeError, RuntimeError, ImportError):
        pass
    return set()


def _agent_status() -> str:
    try:
        import bpy  # type: ignore

        scene = getattr(bpy.context, "scene", None)
        props = getattr(scene, "blender_ai", None)
        if props is not None:
            return str(getattr(props, "agent_status", "IDLE"))
    except (AttributeError, RuntimeError, ImportError):
        pass
    return "UNKNOWN"


def dispatch(request: Dict[str, Any]) -> Dict[str, Any]:
    req_id = request.get("id", "0")
    tool_id = request.get("tool", "")
    params = request.get("params", {}) or {}
    started = time.time()

    def done(ok: bool, result=None, error=None):
        return make_response(
            req_id, ok, result, error,
            duration_ms=int((time.time() - started) * 1000),
        )

    try:
        denied = set(_denied_override) | _denied_from_prefs()
        if tool_id in denied:
            return done(False, None, make_error(
                "TOOL_DENIED", f"Tool '{tool_id}' is denied by configuration."))

        # -- System tools --------------------------------------------------
        if tool_id == "system.ping":
            try:
                import bpy  # type: ignore

                blender = getattr(bpy.app, "version_string", "unknown")
            except ImportError:
                blender = "unavailable (no bpy)"
            if isinstance(params, dict) and params.get("client") == "mcp":
                try:
                    from . import server as _server
                    _server.note_mcp_heartbeat()
                except (ImportError, AttributeError, RuntimeError):
                    pass
            return done(True, {
                "pong": True, "blender": blender,
                "bridge": "blender_ai_connection",
                "agent": _agent_status(),
            })

        if tool_id == "system.tools":
            from ..tools import tools_manifest
            return done(True, {"tools": tools_manifest()})

        if tool_id == "system.modes":
            from ..modes import modes_manifest
            return done(True, {"modes": modes_manifest()})

        if tool_id == "agent.plan":
            from ..agent.planner import build_plan
            task = (params.get("task") or "").strip()
            mode = (params.get("mode") or "SMART").upper()
            if not task:
                return done(False, None, make_error(
                    "INVALID_PARAMS", "agent.plan requires a non-empty 'task'."))
            plan = build_plan(task, mode)
            return done(True, {"plan": plan})

        if tool_id == "agent.execute":
            from ..agent.executor import run_sync
            task = (params.get("task") or "").strip()
            mode = (params.get("mode") or "SMART").upper()
            if not task:
                return done(False, None, make_error(
                    "INVALID_PARAMS", "agent.execute requires a non-empty 'task'."))
            try:
                max_steps = int(params.get("max_steps", 60))
            except (TypeError, ValueError):
                max_steps = 60
            summary = run_sync(task, mode=mode, max_steps=max_steps)
            ok = summary.get("failed", 0) == 0
            return done(ok, {"summary": summary})

        # -- Regular tools -------------------------------------------------
        from ..tools import get_tool, validate_params

        tool = get_tool(tool_id)
        if tool is None:
            if tool_id in SYSTEM_TOOLS:
                return done(False, None, make_error(
                    "INTERNAL_ERROR", f"System tool '{tool_id}' failed to route."))
            return done(False, None, make_error(
                "TOOL_NOT_FOUND",
                f"Unknown tool '{tool_id}'. Call system.tools for the manifest.",
                {"tool": tool_id}))

        cleaned, err = validate_params(params, tool.get("params", {}))
        if err:
            return done(False, None, make_error(
                "INVALID_PARAMS", f"Tool '{tool_id}': {err}.",
                {"tool": tool_id}))

        logger.debug(f"Dispatch: {tool_id} {cleaned}")
        result = tool["func"](cleaned)
        if result is None:
            result = {}
        if not isinstance(result, dict):
            result = {"value": result}
        return done(True, result)

    except Exception as exc:  # noqa: BLE001 - dispatcher must never raise
        # Structured tool failure?
        code = getattr(exc, "code", "INTERNAL_ERROR")
        details = dict(getattr(exc, "details", {}) or {})
        if code == "INTERNAL_ERROR":
            logger.error(f"Dispatcher exception on '{tool_id}': {exc}\n{traceback.format_exc()}")
            details["traceback_tail"] = traceback.format_exc(limit=3)
        else:
            logger.warning(f"Tool '{tool_id}' failed [{code}]: {exc}")
        return done(False, None, make_error(code, str(exc), details))
