#!/usr/bin/env python3
"""Terminal LLM agent — real AI models driving Blender over the TCP bridge.

Providers: openai (ChatGPT), deepseek, gemini, moonshot (Kimi),
anthropic (Claude), custom (proxies like gpt.crax.lol, Ollama, LM Studio).

Examples:
    python agent_runner/llm.py providers
    export DEEPSEEK_API_KEY=sk-...
    python agent_runner/llm.py run --provider deepseek --task "Create a robot"
    python agent_runner/llm.py run --provider custom --base-url https://gpt.crax.lol/v1 \\
        --model gpt-4o --api-key $PROXY_KEY --task "Model a sword"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "mcp_server"))

from blender_ai_connection.llm import (  # noqa: E402
    LlmError,
    list_providers,
    llm_manifest,
    resolve_config,
    run_loop,
)
from blender_ai_connection.llm.client import chat  # noqa: E402
from blender_client import BlenderClient, BlenderError  # noqa: E402


def cmd_providers(_args) -> int:
    for info in list_providers():
        print(f"{info['id']:<10} {info['label']}")
        print(f"           model={info['model']}  endpoint={info['base_url'] or '(set me)'}")
        print(f"           key env: {' / '.join(info['key_env'])}")
    return 0


def cmd_run(args) -> int:
    try:
        cfg = resolve_config(args.provider, args.model, args.api_key or "",
                             args.base_url or "")
    except LlmError as exc:
        print(f"config [{exc.code}]: {exc.message}", file=sys.stderr)
        return 2
    client = BlenderClient(args.host, args.port)
    try:
        pong = client.ping()
        print(f"bridge: Blender {pong.get('blender')} @ {args.host}:{args.port}")
    except BlenderError as exc:
        print(f"[{exc.code}] {exc.message}", file=sys.stderr)
        return 1
    print(f"model: {cfg['label']} / {cfg['model']}  |  mode: {args.mode}  |  "
          f"max {args.max_iters} iterations")

    def exec_fn(tool: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = client.call(tool, tool_args or {}, timeout=600)
            return {"ok": True, "result": result, "error": None}
        except BlenderError as exc:
            return {"ok": False, "result": None,
                    "error": {"code": exc.code, "message": exc.message}}

    def on_event(kind: str, data: Any) -> None:
        if kind == "assistant_text":
            print(f"\n[model] {str(data)[:800]}")
        elif kind == "tool_start":
            print(f"  → {data.get('name')} "
                  f"{json.dumps(data.get('args', {}), default=str)[:160]}")
        elif kind == "tool_result":
            mark = "✔" if data.get("ok") else "✘"
            print(f"  [{mark}] {data.get('name')}: {data.get('text', '')[:200]}")
        elif kind == "error":
            print(f"  [error] {data}")

    outcome = run_loop(args.task, mode=args.mode, cfg=cfg,
                       manifest=llm_manifest(),
                       chat_fn=lambda m, t: chat(cfg, m, t, timeout=180),
                       exec_fn=exec_fn, max_iters=args.max_iters,
                       on_event=on_event)
    print(f"\n stopped={outcome['stopped']} turns={outcome['turns']} "
          f"calls={outcome['tool_calls']} errors={outcome['tool_errors']}")
    print(f" final: {outcome['final'][:2000]}")
    return 0 if outcome["stopped"] in ("done", "max_iters") else 1


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Blender LLM terminal agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("providers", help="List supported AI providers")
    p = sub.add_parser("run", help="Run a task with a real AI model")
    p.add_argument("--task", required=True)
    p.add_argument("--provider", default="openai")
    p.add_argument("--model", default="")
    p.add_argument("--api-key", default="")
    p.add_argument("--base-url", default="")
    p.add_argument("--mode", default="SMART")
    p.add_argument("--max-iters", type=int, default=25)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9876)
    args = parser.parse_args(argv)
    try:
        return {"providers": cmd_providers, "run": cmd_run}[args.command](args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
