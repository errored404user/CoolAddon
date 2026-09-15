"""Tool-manifest -> provider function-schema converters (pure Python)."""

from __future__ import annotations

import json
from typing import Any, Dict, List

TYPE_MAP = {"string": {"type": "string"}, "int": {"type": "integer"},
            "float": {"type": "number"}, "bool": {"type": "boolean"},
            "list": {"type": "array"}, "dict": {"type": "object"}, "any": {}}


def to_json_schema(params_spec: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Our param spec -> JSON Schema object (shared by MCP + LLM paths)."""
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for name, rule in (params_spec or {}).items():
        schema: Dict[str, Any] = dict(TYPE_MAP.get(rule.get("type", "any"), {}))
        if rule.get("description"):
            schema["description"] = rule["description"]
        if "default" in rule:
            try:
                json.dumps(rule["default"])
                schema["default"] = rule["default"]
            except (TypeError, ValueError):
                pass
        if rule.get("choices"):
            schema["enum"] = list(rule["choices"])
        properties[name] = schema
        if rule.get("required"):
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def openai_tools(manifest: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"type": "function",
             "function": {"name": t["id"],
                          "description": t.get("description", t["id"])[:900],
                          "parameters": to_json_schema(t.get("params", {}))}}
            for t in manifest]


def anthropic_tools(manifest: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"name": t["id"],
             "description": t.get("description", t["id"])[:900],
             "input_schema": to_json_schema(t.get("params", {}))}
            for t in manifest]


def gemini_tools(manifest: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"function_declarations": [
        {"name": t["id"],
         "description": t.get("description", t["id"])[:900],
         "parameters": to_json_schema(t.get("params", {}))}
        for t in manifest]}]
