"""Blender-side LLM runner: real AI models driving Blender tools.

Threading (Blender-safe):
- HTTP + model loop run on a background worker thread (never blocks the UI).
- Every tool call is queued to the main thread and executed through the
  same validated dispatcher as everything else, one per timer tick.

Also provides :func:`run_llm_sync` for the bridge (``agent.execute`` with
``use_llm``), where the caller already runs on the main thread.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Dict, Tuple

from ..core import logger
from ..llm import LlmError, LoopAbort, llm_manifest, resolve_config, run_loop

_LLM_JOB: Dict[str, Any] = None  # type: ignore
_TIMER_REGISTERED = False
_PENDING: "queue.Queue[Dict[str, Any]]" = queue.Queue()
_TICK_INTERVAL = 0.05


# ---------------------------------------------------------------------------
# Blender access (guarded)
# ---------------------------------------------------------------------------

def _props():
    try:
        import bpy  # type: ignore
        scene = getattr(bpy.context, "scene", None)
        return getattr(scene, "blender_ai", None)
    except (AttributeError, RuntimeError, ImportError):
        return None


def _set_progress(fraction: float, current: str, status: str = None) -> None:
    props = _props()
    if props is None:
        return
    try:
        props.agent_progress = max(0.0, min(1.0, fraction))
        props.agent_current_step = (current or "")[:500]
        if status:
            props.agent_status = status
        if current:
            props.llm_status = current[:500]
    except (AttributeError, RuntimeError, TypeError):
        pass


def _push_history(name: str, status: str, message: str) -> None:
    props = _props()
    if props is None:
        return
    try:
        item = props.history.add()
        item.name = (name or "")[:200]
        item.status = status
        item.message = (message or "")[:1000]
        while len(props.history) > 100:
            props.history.remove(0)
    except (AttributeError, RuntimeError, TypeError):
        pass


def _denied():
    try:
        from ..core import dispatcher as _dispatcher
        return _dispatcher.current_denied()
    except (ImportError, AttributeError):
        return set()


# ---------------------------------------------------------------------------
# Async (START AGENT with LLM source)
# ---------------------------------------------------------------------------

def llm_busy() -> bool:
    return bool(_LLM_JOB is not None and _LLM_JOB.get("status") == "RUNNING")


def start_llm_async(task: str, mode: str = "SMART", provider_id: str = "openai",
                    model: str = "", api_key: str = "", base_url: str = "",
                    max_iters: int = 25) -> Tuple[bool, str]:
    global _LLM_JOB, _TIMER_REGISTERED
    if llm_busy():
        return False, "LLM agent is already running."
    try:
        import bpy  # type: ignore
    except ImportError:
        return False, "Async LLM agent needs Blender."
    try:
        cfg = resolve_config(provider_id, model, api_key, base_url)
    except LlmError as exc:
        return False, f"LLM config [{exc.code}]: {exc.message}"
    try:
        manifest = llm_manifest()
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not build tool manifest: {exc}"
    max_iters = max(1, min(int(max_iters or 25), 200))
    _LLM_JOB = {"task": task, "mode": mode, "cfg": cfg, "manifest": manifest,
                "denied": _denied(), "max_iters": max_iters,
                "status": "RUNNING", "cancel_requested": False,
                "outcome": None, "started": time.time(),
                "tools_done": 0, "tools_failed": 0, "last_text": ""}
    props = _props()
    if props is not None:
        try:
            props.history.clear()
            props.agent_summary = ""
        except (AttributeError, RuntimeError, TypeError):
            pass
    _set_progress(0.0, f"Contacting {cfg['label']} ({cfg['model']})…", "RUNNING")
    logger.info(f"LLM agent started: [{mode}] {cfg['id']}/{cfg['model']}: {task[:120]}")
    worker = threading.Thread(target=_worker, args=(_LLM_JOB,),
                              name="BlenderAILLM", daemon=True)
    worker.start()
    if not _TIMER_REGISTERED:
        try:
            bpy.app.timers.register(_llm_tick, first_interval=_TICK_INTERVAL)
            _TIMER_REGISTERED = True
        except (AttributeError, RuntimeError, ValueError) as exc:
            _LLM_JOB = None
            return False, f"Could not start LLM timer: {exc}"
    return True, f"LLM agent started ({cfg['label']} / {cfg['model']})."


def _worker(job: Dict[str, Any]) -> None:
    from ..llm.client import chat

    cfg, manifest = job["cfg"], job["manifest"]

    def chat_fn(messages, tools):
        if job.get("cancel_requested"):
            raise LoopAbort()
        job["last_text"] = "Thinking…"
        return chat(cfg, messages, tools, timeout=180)

    def exec_fn(tool, args):
        if job.get("cancel_requested"):
            raise LoopAbort()
        slot: Dict[str, Any] = {}
        event = threading.Event()
        _PENDING.put({"tool": tool, "args": args, "event": event, "slot": slot})
        while not event.wait(timeout=0.2):
            if job.get("cancel_requested"):
                raise LoopAbort()
        if job.get("cancel_requested"):
            raise LoopAbort()
        return slot.get("response", {"ok": False, "result": None,
                                     "error": {"code": "TOOL_FAILED",
                                               "message": "Cancelled."}})

    def on_event(kind, data):
        if kind == "assistant_text" and isinstance(data, str):
            job["last_text"] = data[:300]
        elif kind == "tool_result" and isinstance(data, dict):
            job["tools_done"] += 1
            if not data.get("ok"):
                job["tools_failed"] += 1

    try:
        outcome = run_loop(job["task"], mode=job["mode"], cfg=cfg,
                           manifest=manifest, chat_fn=chat_fn,
                           exec_fn=exec_fn, max_iters=job["max_iters"],
                           denied=list(job["denied"]), on_event=on_event)
    except Exception as exc:  # noqa: BLE001 - worker must always report back
        logger.error(f"LLM worker failure: {exc}")
        outcome = {"final": f"Runner failure: {exc}", "turns": 0,
                   "tool_calls": job["tools_done"],
                   "tool_errors": job["tools_failed"], "stopped": "error"}
    job["outcome"] = outcome
    job["status"] = "FINISHED"


def _llm_tick():
    global _LLM_JOB, _TIMER_REGISTERED
    from ..core import dispatcher as _dispatcher

    job = _LLM_JOB
    if job is None:
        _TIMER_REGISTERED = False
        return None
    if job.get("cancel_requested") and job.get("status") == "RUNNING":
        _finalize_llm(job, "CANCELLED")
        _TIMER_REGISTERED = False
        return None
    # One queued tool call per tick keeps Blender responsive.
    try:
        item = _PENDING.get_nowait()
    except queue.Empty:
        item = None
    if item is not None:
        if job.get("cancel_requested") or job.get("status") != "RUNNING":
            item["slot"]["response"] = {"ok": False, "result": None,
                                        "error": {"code": "TOOL_FAILED",
                                                  "message": "Cancelled."}}
            item["event"].set()
        else:
            tool, args = item["tool"], item["args"]
            _set_progress(_fraction(job), f"{tool}…")
            response = _dispatcher.dispatch(
                {"id": f"llm-{job['tools_done']}", "tool": tool,
                 "params": args if isinstance(args, dict) else {},
                 "timeout": 600})
            if response.get("ok"):
                _push_history(tool, "OK", _short(response.get("result")))
            else:
                err = response.get("error") or {}
                _push_history(tool, "FAILED",
                              f"[{err.get('code')}] {err.get('message')}")
            item["slot"]["response"] = {"ok": bool(response.get("ok")),
                                        "result": response.get("result"),
                                        "error": response.get("error")}
            item["event"].set()
    if job.get("status") == "FINISHED":
        stopped = (job.get("outcome") or {}).get("stopped", "done")
        _finalize_llm(job, {"done": "DONE", "max_iters": "DONE",
                            "aborted": "CANCELLED"}.get(stopped, "ERROR"))
        _TIMER_REGISTERED = False
        return None
    _set_progress(_fraction(job), job.get("last_text") or "Working…")
    return _TICK_INTERVAL


def _fraction(job: Dict[str, Any]) -> float:
    done = job.get("tools_done", 0)
    cap = max(1, job.get("max_iters", 25))
    return min(0.95, done / (cap + 2))


def _short(result: Any, cap: int = 300) -> str:
    import json as _json
    if result is None:
        return "ok"
    try:
        return _json.dumps(result, default=str)[:cap]
    except (TypeError, ValueError):
        return "ok"


def _finalize_llm(job: Dict[str, Any], status: str) -> None:
    # Unblock the worker if it is still waiting (cancel path).
    drained = 0
    while True:
        try:
            item = _PENDING.get_nowait()
        except queue.Empty:
            break
        item["slot"]["response"] = {"ok": False, "result": None,
                                    "error": {"code": "TOOL_FAILED",
                                              "message": "Cancelled."}}
        item["event"].set()
        drained += 1
    job["status"] = status
    outcome = job.get("outcome") or {}
    final = (outcome.get("final") or "").strip()
    tools_done = job.get("tools_done", 0)
    failed = job.get("tools_failed", 0)
    ms = int((time.time() - job.get("started", time.time())) * 1000)
    if status == "CANCELLED":
        current, summary = "Cancelled by user.", f"Cancelled after {tools_done} tool calls."
    elif status == "DONE":
        current = "Task completed."
        summary = f"[LLM {job['cfg']['id']}] {tools_done} calls, {failed} failed ({ms // 1000}s)."
    else:
        current = "LLM run failed."
        summary = f"[LLM {job['cfg']['id']}] ERROR: {final[:300]}"
    _set_progress(1.0 if status == "DONE" else _fraction(job), current, status)
    props = _props()
    if props is not None:
        try:
            props.agent_summary = (summary + (f" — {final[:400]}" if final and status == "DONE" else ""))[:900]
        except (AttributeError, RuntimeError, TypeError):
            pass
    logger.info(f"LLM agent {status.lower()}: {summary} (drained {drained} queued).")


def cancel_llm() -> None:
    if _LLM_JOB is not None and _LLM_JOB.get("status") == "RUNNING":
        _LLM_JOB["cancel_requested"] = True
        logger.info("LLM agent cancellation requested.")


def shutdown_llm_timer() -> None:
    global _LLM_JOB, _TIMER_REGISTERED
    if _LLM_JOB is not None:
        _LLM_JOB["cancel_requested"] = True
        _LLM_JOB = None
    while True:
        try:
            item = _PENDING.get_nowait()
        except queue.Empty:
            break
        try:
            item["event"].set()
        except (AttributeError, RuntimeError):
            pass
    if _TIMER_REGISTERED:
        try:
            import bpy  # type: ignore
            try:
                bpy.app.timers.unregister(_llm_tick)
            except ValueError:
                pass
        except ImportError:
            pass
        _TIMER_REGISTERED = False


# ---------------------------------------------------------------------------
# Sync (bridge agent.execute with use_llm — already on the main thread)
# ---------------------------------------------------------------------------

def run_llm_sync(task: str, mode: str = "SMART",
                 llm_config: Dict[str, Any] = None,
                 max_steps: int = 60) -> Dict[str, Any]:
    from ..core import dispatcher as _dispatcher

    started = time.time()
    llm_config = llm_config or {}
    try:
        cfg = resolve_config(llm_config.get("provider", "openai"),
                             llm_config.get("model", ""),
                             llm_config.get("api_key", ""),
                             llm_config.get("base_url", ""))
    except LlmError as exc:
        return {"task": task, "mode": mode, "engine": "llm",
                "total": 0, "done": 0, "failed": 1, "stopped": "error",
                "final": f"LLM config [{exc.code}]: {exc.message}",
                "results": [], "duration_ms": 0}
    manifest = llm_manifest()
    denied = _denied()
    max_iters = max(1, min(int(llm_config.get("max_iters", 25) or 25),
                           max(1, max_steps)))
    records = []
    logger.info(f"LLM agent started (sync): [{mode}] {cfg['id']}/{cfg['model']}")
    _set_progress(0.0, f"Contacting {cfg['label']}…", "RUNNING")

    def exec_fn(tool, args):
        response = _dispatcher.dispatch(
            {"id": "llm-sync", "tool": tool,
             "params": args if isinstance(args, dict) else {}, "timeout": 600})
        ok = bool(response.get("ok"))
        records.append({"tool": tool, "status": "OK" if ok else "FAILED"})
        _push_history(tool, "OK" if ok else "FAILED",
                      _short(response.get("result") or response.get("error")))
        return {"ok": ok, "result": response.get("result"),
                "error": response.get("error")}

    def on_event(kind, data):
        if kind == "tool_start" and isinstance(data, dict):
            _set_progress(min(0.95, len(records) / (max_iters + 2)),
                          f"{data.get('name')}…")
        elif kind == "assistant_text" and isinstance(data, str):
            _set_progress(min(0.95, len(records) / (max_iters + 2)),
                          data[:300])

    from ..llm.client import chat
    outcome = run_loop(task, mode=mode, cfg=cfg, manifest=manifest,
                       chat_fn=lambda m, t: chat(cfg, m, t, timeout=180),
                       exec_fn=exec_fn, max_iters=max_iters,
                       denied=list(denied), on_event=on_event)
    failed = outcome.get("tool_errors", 0)
    status = {"done": "DONE", "max_iters": "DONE"}.get(
        outcome.get("stopped"), "ERROR")
    summary = {"task": task, "mode": mode, "engine": "llm",
               "provider": cfg["id"], "model": cfg["model"],
               "total": outcome.get("tool_calls", 0),
               "done": outcome.get("tool_calls", 0), "failed": failed,
               "turns": outcome.get("turns", 0),
               "stopped": outcome.get("stopped"),
               "final": outcome.get("final"), "results": records,
               "duration_ms": int((time.time() - started) * 1000)}
    _set_progress(1.0 if status == "DONE" else 0.5,
                  "Task completed." if status == "DONE" else "LLM run failed.",
                  status)
    props = _props()
    if props is not None:
        try:
            props.agent_summary = (f"[LLM {cfg['id']}] {summary['done']} calls, "
                                   f"{failed} failed — {(summary['final'] or '')[:400]}")[:900]
        except (AttributeError, RuntimeError, TypeError):
            pass
    return summary
