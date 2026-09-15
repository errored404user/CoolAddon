"""Tool registry + base helpers.

Pure Python (no bpy at import time) so the registry, parameter specs and
validation can be reused by the MCP server, agent runner and tests.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ToolError(Exception):
    """Raised by tool implementations to report a clean, structured failure."""

    def __init__(self, code: str = "TOOL_FAILED", message: str = "Tool failed",
                 details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = str(message)
        self.details = details or {}


def require_bpy():
    """Return bpy or raise a structured ToolError (keeps workers testable)."""
    try:
        import bpy  # type: ignore
        return bpy
    except ImportError:
        raise ToolError("BLENDER_UNAVAILABLE", "This tool requires Blender (bpy).")


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------

_NUM_TYPES = (int, float)
_TYPE_NAMES = ("string", "int", "float", "bool", "list", "dict", "any")


def _coerce(value: Any, want: str):
    if want == "any":
        return value, None
    if want == "string":
        if isinstance(value, str):
            return value, None
        return str(value), None
    if want == "bool":
        if isinstance(value, bool):
            return value, None
        if isinstance(value, (int, float)):
            return bool(value), None
        if isinstance(value, str):
            low = value.strip().lower()
            if low in ("true", "1", "yes", "y"):
                return True, None
            if low in ("false", "0", "no", "n"):
                return False, None
        return value, "expected bool"
    if want == "int":
        if isinstance(value, bool):
            return int(value), None
        if isinstance(value, int):
            return value, None
        if isinstance(value, float) and value.is_integer():
            return int(value), None
        return value, "expected int"
    if want == "float":
        if isinstance(value, bool):
            return float(value), None
        if isinstance(value, (int, float)):
            return float(value), None
        return value, "expected float"
    if want == "list":
        if isinstance(value, (list, tuple)):
            return list(value), None
        return value, "expected list"
    if want == "dict":
        if isinstance(value, dict):
            return value, None
        return value, "expected object/dict"
    return value, f"unknown spec type '{want}'"


def validate_params(params: Dict[str, Any],
                    spec: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Validate + apply defaults. Returns (cleaned, error_message|None)."""
    cleaned: Dict[str, Any] = {}
    spec = spec or {}
    for name, rule in spec.items():
        want = rule.get("type", "any")
        required = bool(rule.get("required", False))
        has_default = "default" in rule
        if name not in params or params[name] is None:
            if required and not has_default:
                return {}, f"missing required param '{name}'"
            if has_default:
                cleaned[name] = rule["default"]
            continue
        coerced, err = _coerce(params[name], want)
        if err:
            return {}, f"param '{name}': {err}"
        cleaned[name] = coerced
        # Enum constraint
        choices = rule.get("choices")
        if choices and cleaned[name] not in choices:
            return {}, f"param '{name}': must be one of {choices}"
    # Pass through unknown params untouched (forward-compat), but keep them.
    for key, value in params.items():
        if key not in cleaned:
            cleaned[key] = value
    return cleaned, None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

TOOL_CATEGORIES = [
    ("scene", "Scene"),
    ("modeling", "Modeling"),
    ("material", "Materials"),
    ("animation", "Animation"),
    ("camera", "Camera"),
    ("lighting", "Lighting"),
    ("rendering", "Rendering"),
    ("nodes", "Nodes"),
    ("physics", "Physics"),
    ("project", "Project"),
    ("character", "Character"),
    ("environment", "Environment"),
    ("procedural", "Procedural"),
    ("optimization", "Optimization"),
    ("debug", "Debug"),
    ("cutscene", "Cutscene"),
]


def register_tool(tool_id: str, category: str, label: str,
                  description: str = "", params: Optional[Dict[str, Dict[str, Any]]] = None):
    """Decorator used by tool modules to register themselves."""

    def deco(func: Callable[[Dict[str, Any]], Dict[str, Any]]):
        TOOL_REGISTRY[tool_id] = {
            "id": tool_id,
            "category": category,
            "label": label,
            "description": description or label,
            "params": params or {},
            "func": func,
        }
        return func

    return deco


def get_tool(tool_id: str) -> Optional[Dict[str, Any]]:
    return TOOL_REGISTRY.get(tool_id)


def list_tools(category: Optional[str] = None) -> List[Dict[str, Any]]:
    tools = sorted(TOOL_REGISTRY.values(), key=lambda t: t["id"])
    if category:
        tools = [t for t in tools if t["category"] == category]
    return tools


def tools_manifest() -> List[Dict[str, Any]]:
    """JSON-serializable manifest (no function refs) for MCP / UI / tests."""
    manifest = []
    for tool in list_tools():
        manifest.append({
            "id": tool["id"],
            "category": tool["category"],
            "label": tool["label"],
            "description": tool["description"],
            "params": tool["params"],
        })
    return manifest
