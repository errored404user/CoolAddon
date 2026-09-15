#!/usr/bin/env python3
"""Blender MCP server: exposes Blender AI tools to MCP-capable AI clients.

Transport to the AI client: stdio (JSON-RPC 2.0, MCP shape).
Transport to Blender: TCP bridge (see ``blender_client.py``).

- If the official ``mcp`` package is installed, it is used.
- Otherwise a dependency-free minimal JSON-RPC implementation handles the
  core MCP flow (initialize / tools/list / tools/call), which is enough for
  Claude Desktop and other standard MCP clients.

Usage:
    python server.py --host 127.0.0.1 --port 9876
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_client import BlenderClient, BlenderError  # noqa: E402


def _log(message: str) -> None:
    print(f"[blender-mcp] {message}", file=sys.stderr, flush=True)


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from blender_ai_connection.llm.schema import to_json_schema  # shared
except ImportError:

    def to_json_schema(params_spec):  # standalone fallback (no repo root)
        _MAP = {"string": {"type": "string"}, "int": {"type": "integer"},
                "float": {"type": "number"}, "bool": {"type": "boolean"},
                "list": {"type": "array"}, "dict": {"type": "object"},
                "any": {}}
        properties, required = {}, []
        for _name, _rule in (params_spec or {}).items():
            _schema = dict(_MAP.get(_rule.get("type", "any"), {}))
            if _rule.get("description"):
                _schema["description"] = _rule["description"]
            if "default" in _rule:
                try:
                    json.dumps(_rule["default"])
                    _schema["default"] = _rule["default"]
                except (TypeError, ValueError):
                    pass
            if _rule.get("choices"):
                _schema["enum"] = list(_rule["choices"])
            properties[_name] = _schema
            if _rule.get("required"):
                required.append(_name)
        return {"type": "object", "properties": properties,
                "required": required}


def static_manifest() -> List[Dict[str, Any]]:
    """Tool manifest without needing Blender (imports the pure-python registry)."""
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    try:
        from blender_ai_connection.tools import tools_manifest
        return tools_manifest()
    except Exception as exc:  # noqa: BLE001
        _log(f"static manifest unavailable: {exc}")
        return []


class Bridge:
    """Blender connection + cached manifest + heartbeat."""

    def __init__(self, host: str, port: int, heartbeat: int):
        self.client = BlenderClient(host, port)
        self._manifest: List[Dict[str, Any]] = []
        self._manifest_at = 0.0
        if heartbeat > 0:
            thread = threading.Thread(target=self._heartbeat_loop,
                                      args=(heartbeat,), daemon=True,
                                      name="mcp-heartbeat")
            thread.start()

    def _heartbeat_loop(self, interval: int) -> None:
        while True:
            try:
                self.client.ping()
            except BlenderError:
                pass
            time.sleep(interval)

    def tools(self) -> List[Dict[str, Any]]:
        if self._manifest and time.time() - self._manifest_at < 60:
            return self._manifest
        try:
            live = self.client.get_tools()
            if live:
                self._manifest, self._manifest_at = live, time.time()
                return live
        except BlenderError as exc:
            _log(f"Blender offline ({exc.message}) — using static manifest.")
        if not self._manifest:
            self._manifest = static_manifest()
        return self._manifest

    def call(self, tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
        timeout = 900 if tool == "agent.execute" else 300
        return self.client.call(tool, params or {}, timeout=timeout)


# ---------------------------------------------------------------------------
# Backend 1: official MCP SDK (preferred when installed)
# ---------------------------------------------------------------------------

def run_with_sdk(bridge: Bridge) -> None:
    import asyncio

    from mcp.server import Server  # type: ignore
    from mcp.server.stdio import stdio_server  # type: ignore
    import mcp.types as types  # type: ignore

    server = Server("blender-ai-connection")

    @server.list_tools()  # type: ignore[misc]
    async def _list_tools() -> List[types.Tool]:
        return [types.Tool(name=t["id"], description=t.get("description", t["id"]),
                           inputSchema=to_json_schema(t.get("params", {})))
                for t in bridge.tools()]

    @server.call_tool()  # type: ignore[misc]
    async def _call_tool(name: str, arguments: Dict[str, Any]):
        try:
            result = bridge.call(name, arguments or {})
            text = json.dumps(result, indent=2, default=str)
            return [types.TextContent(type="text", text=text)]
        except BlenderError as exc:
            text = f"[{exc.code}] {exc.message}"
            return [types.TextContent(type="text", text=text)]

    async def _main() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    _log("using official MCP SDK backend")
    asyncio.run(_main())


# ---------------------------------------------------------------------------
# Backend 2: minimal dependency-free JSON-RPC stdio (MCP-shaped)
# ---------------------------------------------------------------------------

def _rpc_response(mid: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _rpc_error(mid: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": mid, "error": error}


def run_minimal(bridge: Bridge) -> None:
    _log("using minimal JSON-RPC backend (pip install mcp for the full SDK)")
    stdin = sys.stdin
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}
        # Notifications (no id) need no reply.
        if method.startswith("notifications/") or mid is None:
            continue
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "blender-ai-connection",
                                   "version": "1.0.0"},
                }
                _send(_rpc_response(mid, result))
            elif method in ("tools/list", "tools/list_tools"):
                tools = [{"name": t["id"],
                          "description": t.get("description", t["id"]),
                          "inputSchema": to_json_schema(t.get("params", {}))}
                         for t in bridge.tools()]
                tools += [
                    {"name": "agent.plan",
                     "description": "Plan a natural-language task (no execution).",
                     "inputSchema": {"type": "object",
                                     "properties": {"task": {"type": "string"},
                                                    "mode": {"type": "string"}},
                                     "required": ["task"]}},
                    {"name": "agent.execute",
                     "description": "Plan AND execute a natural-language task in Blender.",
                     "inputSchema": {"type": "object",
                                     "properties": {"task": {"type": "string"},
                                                    "mode": {"type": "string"}},
                                     "required": ["task"]}},
                ]
                _send(_rpc_response(mid, {"tools": tools}))
            elif method in ("tools/call", "tools/call_tool"):
                name = params.get("name", "")
                arguments = params.get("arguments") or {}
                try:
                    result = bridge.call(name, arguments)
                    text = json.dumps(result, indent=2, default=str)
                except BlenderError as exc:
                    text = (f"[{exc.code}] {exc.message}\n\nIf Blender is not "
                            f"reachable, open Blender, enable the Blender AI "
                            f"Connection addon and press Start Server.")
                _send(_rpc_response(
                    mid, {"content": [{"type": "text", "text": text}]}))
            elif method == "ping":
                _send(_rpc_response(mid, {"pong": True}))
            else:
                _send(_rpc_error(mid, -32601, f"Unknown method '{method}'."))
        except Exception as exc:  # noqa: BLE001
            _log(f"handler error: {exc}\n{traceback.format_exc(limit=2)}")
            _send(_rpc_error(mid, -32603, "Internal server error.", str(exc)))


def _send(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Blender AI MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--heartbeat", type=int, default=30,
                        help="Blender ping interval in seconds (0 = off)")
    parser.add_argument("--no-sdk", action="store_true",
                        help="Force the minimal backend even if mcp is installed")
    args = parser.parse_args()

    bridge = Bridge(args.host, args.port, args.heartbeat)
    try:
        bridge.client.ping()
        _log(f"Blender bridge reachable at {args.host}:{args.port}.")
    except BlenderError as exc:
        _log(f"Blender not reachable yet: {exc.message}")
        _log("Start Blender + AI Agent bridge; calls will work once it is up.")

    if not args.no_sdk:
        try:
            import mcp  # noqa: F401
            run_with_sdk(bridge)
            return 0
        except ImportError:
            _log("package 'mcp' not installed — falling back to minimal backend")
        except Exception as exc:  # noqa: BLE001
            _log(f"SDK backend failed ({exc}) — falling back to minimal backend")
    run_minimal(bridge)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
