"""Minimal TCP client for the Blender AI bridge (stdlib only).

Speaks the newline-delimited JSON protocol from
``blender_ai_connection/core/protocol.py`` — reimplemented here so the MCP
server and CLI stay dependency-free and installable anywhere.
"""

from __future__ import annotations

import json
import socket
import uuid
from typing import Any, Dict, Optional


class BlenderError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class BlenderClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 9876,
                 default_timeout: int = 60):
        self.host = host
        self.port = int(port)
        self.default_timeout = default_timeout

    def call(self, tool: str, params: Optional[Dict[str, Any]] = None,
             timeout: Optional[int] = None) -> Dict[str, Any]:
        timeout = self.default_timeout if timeout is None else timeout
        request = {"id": uuid.uuid4().hex[:8], "tool": tool,
                   "params": params or {}, "timeout": timeout}
        payload = (json.dumps(request) + "\n").encode("utf-8")
        try:
            sock = socket.create_connection((self.host, self.port),
                                            timeout=min(timeout, 10))
        except OSError as exc:
            raise BlenderError("BLENDER_UNAVAILABLE",
                               f"Cannot reach Blender bridge at "
                               f"{self.host}:{self.port} — is Blender open with "
                               f"the AI Agent bridge started? ({exc})")
        try:
            sock.settimeout(timeout + 10)
            sock.sendall(payload)
            chunks = []
            with sock.makefile("rb") as stream:
                line = stream.readline(12 * 1024 * 1024)
            if not line:
                raise BlenderError("BLENDER_UNAVAILABLE", "Blender closed the connection.")
            try:
                response = json.loads(line.decode("utf-8"))
            except ValueError:
                raise BlenderError("BLENDER_UNAVAILABLE", "Invalid response from Blender.")
        except socket.timeout:
            raise BlenderError("TIMEOUT", f"Blender timed out on '{tool}'.")
        finally:
            try:
                sock.close()
            except OSError:
                pass
        if not response.get("ok"):
            err = response.get("error") or {}
            raise BlenderError(err.get("code", "TOOL_FAILED"),
                               err.get("message", "Unknown Blender error."),
                               err.get("details"))
        result = response.get("result")
        return result if isinstance(result, dict) else {"value": result}

    def ping(self) -> Dict[str, Any]:
        return self.call("system.ping", {"client": "mcp"}, timeout=10)

    def get_tools(self) -> list:
        return self.call("system.tools", {}, timeout=15).get("tools", [])

    def get_modes(self) -> list:
        return self.call("system.modes", {}, timeout=15).get("modes", [])
