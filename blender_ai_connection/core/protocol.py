"""Wire protocol for the Blender <-> MCP bridge.

Pure Python (no bpy) so it can be shared by the Blender addon,
the MCP server, the agent runner and the test-suite.

Transport: TCP, newline-delimited JSON (one request / one response per line).

Request:
    {"id": "1", "tool": "scene.inspect", "params": {...}, "timeout": 60}

Response (success):
    {"id": "1", "ok": true, "result": {...}, "error": null, "duration_ms": 12}

Response (failure):
    {"id": "1", "ok": false, "result": null,
     "error": {"code": "TOOL_FAILED", "message": "...", "details": {...}},
     "duration_ms": 3}
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


PROTOCOL_VERSION = "1.0"
DEFAULT_TIMEOUT = 60

# Special built-in tools handled by the dispatcher itself.
SYSTEM_TOOLS = ("system.ping", "system.tools", "system.modes", "agent.plan", "agent.execute")

ERROR_CODES = (
    "TOOL_NOT_FOUND",
    "INVALID_REQUEST",
    "INVALID_PARAMS",
    "TOOL_DENIED",
    "TOOL_FAILED",
    "OBJECT_NOT_FOUND",
    "TIMEOUT",
    "BLENDER_UNAVAILABLE",
    "AGENT_BUSY",
    "INTERNAL_ERROR",
)


def make_error(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if code not in ERROR_CODES:
        code = "INTERNAL_ERROR"
    return {"code": code, "message": str(message), "details": details or {}}


def make_response(
    req_id: Any,
    ok: bool,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[Dict[str, Any]] = None,
    duration_ms: int = 0,
) -> Dict[str, Any]:
    return {
        "id": req_id,
        "ok": bool(ok),
        "result": result,
        "error": error,
        "duration_ms": int(duration_ms),
        "protocol": PROTOCOL_VERSION,
    }


def parse_request(data: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Validate an incoming raw object. Returns (request, error)."""
    if not isinstance(data, dict):
        return None, make_error("INVALID_REQUEST", "Request must be a JSON object.")
    tool = data.get("tool")
    if not tool or not isinstance(tool, str):
        return None, make_error("INVALID_REQUEST", "Missing required field 'tool' (string).")
    params = data.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return None, make_error("INVALID_REQUEST", "Field 'params' must be an object.")
    try:
        timeout = int(data.get("timeout", DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return None, make_error("INVALID_REQUEST", "Field 'timeout' must be an integer.")
    timeout = max(1, min(timeout, 1800))
    return {"id": data.get("id", "0"), "tool": tool, "params": params, "timeout": timeout}, None
