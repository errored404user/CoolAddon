#!/usr/bin/env python3
"""Standalone agent CLI — drive Blender from a terminal (no MCP client needed).

Examples:
    python cli.py ping
    python cli.py plan --task "Create a futuristic robot"
    python cli.py run --task "Create a medieval castle environment" --mode ENVIRONMENT
    python cli.py tool --name scene.inspect --params '{}'
    python cli.py tools --category modeling
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_server"))
try:
    from blender_client import BlenderClient, BlenderError
except ImportError:  # pragma: no cover - fallback when layout differs
    BlenderClient = None  # type: ignore
    BlenderError = Exception  # type: ignore


def _plain_call(host: str, port: int, tool: str, params: Dict[str, Any],
                timeout: int) -> Dict[str, Any]:
    """Zero-dependency fallback if blender_client cannot be imported."""
    request = {"id": uuid.uuid4().hex[:8], "tool": tool,
               "params": params, "timeout": timeout}
    sock = socket.create_connection((host, port), timeout=10)
    try:
        sock.settimeout(timeout + 10)
        sock.sendall((json.dumps(request) + "\n").encode())
        with sock.makefile("rb") as stream:
            line = stream.readline(12 * 1024 * 1024)
        response = json.loads(line.decode("utf-8"))
    finally:
        sock.close()
    if not response.get("ok"):
        raise RuntimeError(response.get("error"))
    return response.get("result") or {}


def call(host: str, port: int, tool: str, params: Dict[str, Any],
         timeout: int) -> Dict[str, Any]:
    if BlenderClient is not None:
        return BlenderClient(host, port).call(tool, params, timeout=timeout)
    return _plain_call(host, port, tool, params, timeout)


def cmd_ping(args) -> int:
    print(json.dumps(call(args.host, args.port, "system.ping",
                          {"client": "cli"}, args.timeout), indent=2))
    return 0


def cmd_tools(args) -> int:
    result = call(args.host, args.port, "system.tools", {}, args.timeout)
    tools = result.get("tools", [])
    if args.category:
        tools = [t for t in tools if t["category"] == args.category]
    if args.json:
        print(json.dumps(tools, indent=2))
    else:
        print(f"{len(tools)} tools:")
        for tool in tools:
            print(f"  {tool['id']:<38} {tool['label']}")
    return 0


def cmd_modes(args) -> int:
    print(json.dumps(call(args.host, args.port, "system.modes", {},
                          args.timeout), indent=2))
    return 0


def _print_plan(plan: Dict[str, Any]) -> None:
    print(f"Task: {plan.get('task')}")
    print(f"Mode: {plan.get('mode')}  Domains: {', '.join(plan.get('detected_domains', []))}")
    for note in plan.get("notes", []):
        print(f"Note: {note}")
    print(f"Steps ({len(plan.get('steps', []))}):")
    for step in plan.get("steps", []):
        crit = " [critical]" if step.get("critical") else ""
        print(f"  {step.get('seq'):>3}. {step.get('label')} <{step.get('tool')}>{crit}")


def cmd_plan(args) -> int:
    if not args.task:
        print("error: --task is required", file=sys.stderr)
        return 2
    plan = call(args.host, args.port, "agent.plan",
                {"task": args.task, "mode": args.mode}, args.timeout)["plan"]
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        _print_plan(plan)
    return 0


def cmd_run(args) -> int:
    if not args.task:
        print("error: --task is required", file=sys.stderr)
        return 2
    print(f"Running [{args.mode}] {args.task}")
    summary = call(args.host, args.port, "agent.execute",
                   {"task": args.task, "mode": args.mode,
                    "max_steps": args.max_steps}, args.timeout)["summary"]
    if args.json:
        print(json.dumps(summary, indent=2))
        return 0 if summary.get("failed", 0) == 0 else 1
    for record in summary.get("results", []):
        mark = {"OK": "✔", "RETRIED": "↻", "FAILED": "✘",
                "SKIPPED": "○"}.get(record.get("status"), "?")
        print(f"  [{mark}] {record.get('label')} — {record.get('message', '')[:100]}")
    print(f"Done: {summary['done'] - summary['failed']}/{summary['total']} OK, "
          f"{summary['failed']} failed ({summary['duration_ms']}ms).")
    return 0 if summary.get("failed", 0) == 0 else 1


def cmd_tool(args) -> int:
    try:
        params = json.loads(args.params or "{}")
    except ValueError as exc:
        print(f"error: invalid --params JSON: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(call(args.host, args.port, args.name, params,
                          args.timeout), indent=2, default=str))
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Blender AI agent CLI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--json", action="store_true", help="Raw JSON output")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ping", help="Ping the Blender bridge")
    p = sub.add_parser("tools", help="List tools")
    p.add_argument("--category", default="")
    sub.add_parser("modes", help="List agent modes")
    p = sub.add_parser("plan", help="Show the plan for a task (no execution)")
    p.add_argument("--task", required=True)
    p.add_argument("--mode", default="SMART")
    p = sub.add_parser("run", help="Plan and execute a task")
    p.add_argument("--task", required=True)
    p.add_argument("--mode", default="SMART")
    p.add_argument("--max-steps", type=int, default=60)
    p = sub.add_parser("tool", help="Call a single tool")
    p.add_argument("--name", required=True)
    p.add_argument("--params", default="{}")
    args = parser.parse_args(argv)
    try:
        return {"ping": cmd_ping, "tools": cmd_tools, "modes": cmd_modes,
                "plan": cmd_plan, "run": cmd_run,
                "tool": cmd_tool}[args.command](args)
    except BlenderError as exc:  # type: ignore[misc]
        print(f"[{getattr(exc, 'code', 'ERROR')}] {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
