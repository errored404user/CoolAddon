"""Agentic tool loop: model <-> Blender tools until a final answer.

Pure Python. The loop is transport-agnostic: callers inject ``chat_fn``
(model round-trip) and ``exec_fn`` (tool execution) so the same code runs
inside Blender (main-thread dispatch), over the TCP bridge (CLI), and in
tests (stubs). ``exec_fn`` may raise :class:`LoopAbort` to stop promptly
(e.g. user pressed Cancel).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .providers import LlmError


class LoopAbort(Exception):
    pass


TOOL_RULES = """TOOL RULES (follow strictly):
- The first user message contains a live scene summary. Reuse existing objects, materials and collections instead of recreating them; inspect again with scene.inspect when you need fresh detail.
- Only call tools listed in your function schemas, with exact names and valid params. Unknown tools error out.
- scene.clear needs confirm=true — use it ONLY when the user explicitly asked to clear/delete the scene.
- Prefer fewer, bigger steps. You may call several independent tools in one block; dependent steps must wait for results.
- Verify important work afterwards (scene.inspect / debug.diagnose).
- Never invent file paths, object names, URLs or API keys. If something is missing, say so.
- When done, reply with a concise summary and NO further tool calls."""


def llm_manifest() -> List[Dict[str, Any]]:
    """Tool manifest for LLMs: all real tools + read-only system tools.

    agent.* is excluded on purpose (an LLM must do work itself, not
    recursively spawn the built-in planner).
    """
    from ..tools import tools_manifest
    manifest = [t for t in tools_manifest() if not t["id"].startswith("agent.")]
    manifest += [
        {"id": "system.ping", "category": "system", "label": "Ping bridge",
         "description": "Check the Blender bridge is alive.", "params": {}},
        {"id": "system.tools", "category": "system", "label": "List tools",
         "description": "Return the full tool manifest with param specs.", "params": {}},
        {"id": "system.modes", "category": "system", "label": "List modes",
         "description": "Return agent modes with guidance prompts.", "params": {}},
    ]
    return manifest


def build_system_prompt(mode: str = "SMART", denied: List[str] = None) -> str:
    try:
        from ..modes import get_mode
        info = get_mode(mode) or {}
        mode_prompt = info.get("system_prompt", "")
        label = info.get("label", mode)
    except (ImportError, AttributeError):
        mode_prompt, label = "", mode
    parts = [f"You are a Blender production agent ({label}) with direct tool access to Blender.",
             mode_prompt, TOOL_RULES]
    if denied:
        parts.append("TOOLS DENIED BY CONFIGURATION (do not call): " + ", ".join(denied))
    return "\n\n".join(p for p in parts if p)


def compact_context(result: Any, name_cap: int = 60) -> str:
    """Shrink a scene.inspect result into an LLM-friendly summary."""
    if not isinstance(result, dict) or not result.get("objects_total"):
        return "(Scene context unavailable — call scene.inspect yourself.)"
    lines = [f"Scene '{result.get('scene')}' — {result.get('objects_total')} objects:"]
    by_type = result.get("objects_by_type") or {}
    lines.append("  by type: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    names: List[str] = []
    for entry in result.get("objects") or []:
        if isinstance(entry, dict) and entry.get("name"):
            names.append(f"{entry['name']}({entry.get('type', '?')})")
        if len(names) >= name_cap:
            names.append("…")
            break
    lines.append("  objects: " + (", ".join(names) if names else "(none)"))
    for key in ("materials", "cameras", "lights", "armatures", "collections"):
        values = result.get(key) or []
        lines.append(f"  {key}: " + (", ".join(values[:25]) if values else "(none)"))
    frame = result.get("frame") or {}
    lines.append(f"  frames: {frame.get('start')}-{frame.get('end')} @ "
                 f"{frame.get('fps')}fps (current {frame.get('current')})")
    lines.append(f"  active: {result.get('active')}, selected: "
                 f"{', '.join((result.get('selected') or [])[:10]) or '(none)'}")
    return "\n".join(lines)


def run_loop(task: str, mode: str = "SMART", cfg: Dict[str, Any] = None,
             manifest: List[Dict[str, Any]] = None,
             chat_fn: Callable = None, exec_fn: Callable = None,
             max_iters: int = 25, denied: List[str] = None,
             on_event: Callable = None) -> Dict[str, Any]:
    """Run the agent loop. Returns {final, turns, tool_calls, tool_errors,
    stopped, history}. ``stopped`` is one of done|max_iters|aborted|error."""
    from .client import chat as _default_chat

    if exec_fn is None:
        raise ValueError("run_loop requires exec_fn(tool, args).")
    manifest = manifest if manifest is not None else llm_manifest()
    denied = list(denied or [])
    if chat_fn is None:
        if cfg is None:
            raise ValueError("run_loop requires cfg or chat_fn.")
        chat_fn = lambda messages, tools: _default_chat(cfg, messages, tools)  # noqa: E731
    known = {t["id"] for t in manifest}

    def emit(kind: str, data: Any = None):
        if on_event:
            try:
                on_event(kind, data)
            except Exception:  # noqa: BLE001 - UI callbacks must never break the loop
                pass

    # Turn 0: live scene context (best effort, not an LLM turn).
    try:
        ctx_result = exec_fn("scene.inspect", {"object_limit": 120})
        ctx_text = compact_context((ctx_result or {}).get("result", ctx_result))
    except LoopAbort:
        return {"final": "Cancelled.", "turns": 0, "tool_calls": 0,
                "tool_errors": 0, "stopped": "aborted", "history": []}
    except Exception as exc:  # noqa: BLE001
        ctx_text = f"(scene.inspect failed: {exc} — call it yourself if needed.)"
    emit("context", ctx_text)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "text": build_system_prompt(mode, denied)},
        {"role": "user", "text": f"TASK: {task}\n\nLIVE SCENE:\n{ctx_text}"},
    ]
    calls_made = errors = 0
    for turn in range(1, max_iters + 1):
        try:
            reply = chat_fn(messages, manifest)
        except LoopAbort:
            return {"final": "Cancelled.", "turns": turn - 1,
                    "tool_calls": calls_made, "tool_errors": errors,
                    "stopped": "aborted", "history": messages}
        except LlmError as exc:
            emit("error", f"[{exc.code}] {exc.message}")
            return {"final": f"LLM error [{exc.code}]: {exc.message}",
                    "turns": turn - 1, "tool_calls": calls_made,
                    "tool_errors": errors, "stopped": "error",
                    "history": messages}
        except Exception as exc:  # noqa: BLE001
            emit("error", str(exc))
            return {"final": f"Unexpected chat failure: {exc}",
                    "turns": turn - 1, "tool_calls": calls_made,
                    "tool_errors": errors, "stopped": "error",
                    "history": messages}
        text = (reply.get("text") or "").strip()
        tool_calls = reply.get("tool_calls") or []
        if text:
            emit("assistant_text", text)
        if not tool_calls:
            emit("done", text)
            return {"final": text or "(The model returned an empty reply.)",
                    "turns": turn, "tool_calls": calls_made,
                    "tool_errors": errors, "stopped": "done",
                    "history": messages}
        messages.append({"role": "assistant", "text": text,
                         "tool_calls": tool_calls})
        for call in tool_calls:
            name = call.get("name", "")
            args = call.get("args", {}) or {}
            call_id = call.get("id", f"turn{turn}_{calls_made}")
            emit("tool_start", {"name": name, "args": args})
            if name in denied:
                outcome: Dict[str, Any] = {"ok": False, "result": None,
                                           "error": {"code": "TOOL_DENIED",
                                                     "message": f"'{name}' is denied."}}
            elif name not in known:
                outcome = {"ok": False, "result": None,
                           "error": {"code": "TOOL_NOT_FOUND",
                                     "message": f"Unknown tool '{name}'. Use schema tools only."}}
            else:
                try:
                    outcome = exec_fn(name, args) or {}
                    calls_made += 1
                except LoopAbort:
                    return {"final": "Cancelled.", "turns": turn,
                            "tool_calls": calls_made, "tool_errors": errors,
                            "stopped": "aborted", "history": messages}
                except Exception as exc:  # noqa: BLE001
                    outcome = {"ok": False, "result": None,
                               "error": {"code": "TOOL_FAILED", "message": str(exc)}}
                    calls_made += 1
            if not outcome.get("ok"):
                errors += 1
            import json as _json
            if outcome.get("ok"):
                try:
                    result_text = "OK: " + _json.dumps(outcome.get("result"),
                                                      default=str)[:4000]
                except (TypeError, ValueError):
                    result_text = "OK"
            else:
                err = outcome.get("error") or {}
                result_text = f"FAILED [{err.get('code')}]: {err.get('message')}"
            emit("tool_result", {"name": name, "ok": bool(outcome.get("ok")),
                                 "text": result_text[:500]})
            messages.append({"role": "tool", "text": result_text,
                             "tool_call_id": call_id, "tool_name": name})
    emit("done", f"Stopped after {max_iters} iterations.")
    return {"final": f"(Stopped after {max_iters} tool iterations. Ask to continue if needed.)",
            "turns": max_iters, "tool_calls": calls_made,
            "tool_errors": errors, "stopped": "max_iters",
            "history": messages}
