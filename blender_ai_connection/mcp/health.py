"""Detect whether the MCP side of the bridge is available.

The Blender addon itself runs the TCP bridge; the external MCP server
(``mcp_server/server.py`` in this repo) connects to it and exposes Blender
tools to MCP-capable AI clients (Claude Desktop, etc.).

If anything is missing we return a *useful setup message* instead of
failing silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def _addon_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _repo_guesses():
    root = _addon_root()
    # Dev checkout: <repo>/blender_ai_connection/mcp/health.py
    yield root.parent
    # Installed addon: .../addons/blender_ai_connection/... -> no repo; still check.
    yield root


def _find_repo_file(*parts: str) -> Optional[Path]:
    for base in _repo_guesses():
        candidate = base.joinpath(*parts)
        if candidate.exists():
            return candidate
    return None


def check_mcp_status() -> Dict[str, Any]:
    from ..core import server as _server

    bridge_running = _server.is_running()
    stats = _server.get_stats()

    try:
        import mcp  # type: ignore  # noqa: F401

        mcp_version = getattr(mcp, "__version__", "installed")
        mcp_package: Optional[str] = str(mcp_version)
    except ImportError:
        mcp_package = None

    server_script = _find_repo_file("mcp_server", "server.py")
    config_file = _find_repo_file("config", "config.json")

    problems = []
    if not bridge_running:
        problems.append("Blender bridge is not running (press Start Server).")
    if server_script is None:
        problems.append("mcp_server/server.py not found next to the addon "
                        "(full repo checkout required for MCP mode).")
    if mcp_package is None:
        problems.append("Python package 'mcp' is not installed in the "
                        "environment that will run the MCP server.")

    if not problems:
        status = "Ready"
        summary = (f"Bridge on {stats['host']}:{stats['port']} · "
                   f"mcp {mcp_package} · heartbeat {stats.get('last_mcp_ping') or 'no ping yet'}")
    elif not bridge_running and len(problems) == 1:
        status = "Bridge stopped"
        summary = problems[0]
    else:
        status = "Setup needed"
        summary = " · ".join(problems)

    setup_message = (
        "MCP SETUP — connect an external AI (e.g. Claude Desktop) to Blender:\n"
        "1) In Blender: AI Agent panel → Start Server "
        f"(bridge on {stats['host']}:{stats['port']}).\n"
        "2) On your machine: pip install mcp\n"
        "3) Point your MCP client at this repo's mcp_server/server.py with "
        "--host/--port matching the bridge.\n"
        "   Claude Desktop example (claude_desktop_config.json):\n"
        '   {"mcpServers": {"blender": {"command": "python", '
        '"args": ["/ABS/PATH/CoolAddon/mcp_server/server.py", '
        f'"--host", "{stats["host"]}", "--port", "{stats["port"]}"]}}}}\n'
        "4) Restart the MCP client. Its first tools/list call pings the bridge.\n"
        "Tip: the built-in START AGENT button works WITHOUT any MCP setup — "
        "MCP is only needed for external AI control."
    )

    return {
        "status": status,
        "summary": summary,
        "bridge_running": bridge_running,
        "bridge": f"{stats['host']}:{stats['port']}",
        "last_mcp_ping": stats.get("last_mcp_ping"),
        "mcp_package": mcp_package or "missing",
        "server_script": str(server_script) if server_script else "missing",
        "config": str(config_file) if config_file else "missing",
        "problems": problems,
        "setup_message": setup_message,
    }
