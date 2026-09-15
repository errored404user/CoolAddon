"""Plan executor: sequential steps with validation, retry and feedback.

Two flavors share one step runner:
- :func:`run_sync` — blocking, used by ``agent.execute`` over the bridge.
- :func:`start_async` — one step per timer tick, used by START AGENT so the
  Blender UI never freezes during long productions.
"""

from __future__ import annotations

import time
import traceback
from typing import Any, Dict, List, Optional

from ..core import logger
from .planner import Step, build_plan
from .recovery import suggest_fix

_JOB: Optional[Dict[str, Any]] = None
_TIMER_REGISTERED = False
_TICK_INTERVAL = 0.05


class UnresolvedRef(Exception):
    pass


# ---------------------------------------------------------------------------
# Blender access (all guarded — executor imports cleanly without bpy)
# ---------------------------------------------------------------------------

def _props():
    try:
        import bpy  # type: ignore
        scene = getattr(bpy.context, "scene", None)
        return getattr(scene, "blender_ai", None)
    except (AttributeError, RuntimeError, ImportError):
        return None


def _max_retries() -> int:
    try:
        import bpy  # type: ignore
        prefs = bpy.context.preferences.addons.get("blender_ai_connection")
        if prefs and hasattr(prefs, "preferences"):
            return max(0, min(int(getattr(prefs.preferences, "max_retries", 1)), 5))
    except (AttributeError, RuntimeError, ImportError, ValueError):
        pass
    return 1


def _push_history(name: str, status: str, message: str, duration_ms: int = 0) -> None:
    props = _props()
    if props is None:
        return
    try:
        item = props.history.add()
        item.name = (name or "")[:200]
        item.status = status
        item.message = (message or "")[:1000]
        item.duration_ms = int(duration_ms)
        while len(props.history) > 100:
            props.history.remove(0)
    except (AttributeError, RuntimeError, TypeError):
        pass


def _set_progress(done: int, total: int, current: str,
                  status: Optional[str] = None) -> None:
    props = _props()
    if props is None:
        return
    try:
        props.agent_progress = (done / total) if total else 0.0
        props.agent_current_step = (current or "")[:500]
        if status:
            props.agent_status = status
    except (AttributeError, RuntimeError, TypeError):
        pass


# ---------------------------------------------------------------------------
# Context ($refs)
# ---------------------------------------------------------------------------

def gather_context() -> Dict[str, Any]:
    """Fresh scene snapshot for $ref resolution ({} when unavailable)."""
    try:
        from ..tools.scene_tools import scene_inspect
        return scene_inspect({"object_limit": 400})
    except Exception as exc:  # noqa: BLE001 - context is best-effort
        logger.debug(f"Context gather failed: {exc}")
        return {}


def _lookup_ref(ref: str, ctx: Dict[str, Any]) -> str:
    objects = ctx.get("objects") or []

    def first_of(*types: str) -> Optional[str]:
        for entry in objects:
            if isinstance(entry, dict) and entry.get("type") in types:
                return entry.get("name")
        return None

    if ref == "$active_object":
        if ctx.get("active"):
            return ctx["active"]
        fallback = first_of("MESH")
        if fallback:
            return fallback
    elif ref == "$selected_first":
        selected = ctx.get("selected") or []
        if selected:
            return selected[0]
    elif ref == "$first_mesh":
        found = first_of("MESH")
        if found:
            return found
    elif ref == "$first_camera":
        found = first_of("CAMERA")
        if found:
            return found
    elif ref == "$first_light":
        found = first_of("LIGHT")
        if found:
            return found
    elif ref == "$first_armature":
        found = first_of("ARMATURE")
        if found:
            return found
    elif ref == "$first_object":
        if objects and isinstance(objects[0], dict):
            return objects[0].get("name", "")
    raise UnresolvedRef(
        f"Could not resolve {ref}: no matching object in the scene. "
        "Create or select something first.")


def _resolve(value: Any, ctx: Dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _lookup_ref(value, ctx)
    if isinstance(value, list):
        return [_resolve(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, ctx) for k, v in value.items()}
    return value


def _needs_context(params: Any) -> bool:
    if isinstance(params, str):
        return params.startswith("$")
    if isinstance(params, list):
        return any(_needs_context(v) for v in params)
    if isinstance(params, dict):
        return any(_needs_context(v) for v in params.values())
    return False


# ---------------------------------------------------------------------------
# Step runner (shared)
# ---------------------------------------------------------------------------

def run_step(step: Step, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one plan step with recovery + retry. Returns a result record."""
    from ..core import dispatcher as _dispatcher

    label = step.get("label") or step.get("tool")
    tool_id = step.get("tool", "")
    params = dict(step.get("params") or {})
    started = time.time()

    # Resolve $refs against a fresh snapshot.
    local_ctx = ctx
    if _needs_context(params):
        fresh = gather_context()
        if fresh:
            local_ctx = fresh
            ctx.clear()
            ctx.update(fresh)
    try:
        params = _resolve(params, local_ctx)
    except UnresolvedRef as exc:
        ms = int((time.time() - started) * 1000)
        logger.warning(f"Step '{label}' skipped: {exc}")
        _push_history(label, "SKIPPED", str(exc), ms)
        return {"seq": step.get("seq"), "tool": tool_id, "label": label,
                "status": "SKIPPED", "message": str(exc), "duration_ms": ms}

    attempts = 1 + _max_retries()
    last_error: Optional[Dict[str, Any]] = None
    for attempt in range(1, attempts + 1):
        response = _dispatcher.dispatch(
            {"id": f"agent-{step.get('seq')}-{attempt}", "tool": tool_id,
             "params": params, "timeout": 600})
        if response.get("ok"):
            ms = int((time.time() - started) * 1000)
            status = "RETRIED" if attempt > 1 else "OK"
            logger.info(f"Step {step.get('seq')}/{step.get('total')} {status}: {label}")
            _push_history(label, status, _summarize_result(response.get("result")), ms)
            if tool_id == "scene.inspect" and isinstance(response.get("result"), dict):
                ctx.clear()
                ctx.update(response["result"])
            return {"seq": step.get("seq"), "tool": tool_id, "label": label,
                    "status": status, "message": "ok", "duration_ms": ms,
                    "attempts": attempt}
        last_error = response.get("error") or {}
        fix = suggest_fix(tool_id, params, last_error, local_ctx)
        if fix and attempt < attempts:
            logger.warning(f"Step '{label}' failed ({last_error.get('code')}): "
                           f"{last_error.get('message')} — retrying: {fix['note']}")
            params = fix["params"]
            continue
        break

    ms = int((time.time() - started) * 1000)
    message = f"[{last_error.get('code')}] {last_error.get('message')}" if last_error else "failed"
    logger.warning(f"Step {step.get('seq')}/{step.get('total')} FAILED: {label}: {message}")
    _push_history(label, "FAILED", message, ms)
    return {"seq": step.get("seq"), "tool": tool_id, "label": label,
            "status": "FAILED", "message": message, "duration_ms": ms,
            "attempts": attempts}


def _summarize_result(result: Any, cap: int = 300) -> str:
    import json as _json
    if result is None:
        return "ok"
    if isinstance(result, dict):
        # Prefer meaningful keys for the history line.
        for key in ("name", "character", "preset", "shots", "scattered",
                    "deleted", "assigned", "baked", "fixed", "issues",
                    "rendered_frame", "saved", "filepath"):
            if key in result:
                return f"{key}={str(result[key])[:cap]}"
        try:
            return _json.dumps(result, default=str)[:cap]
        except (TypeError, ValueError):
            return "ok"
    return str(result)[:cap]


# ---------------------------------------------------------------------------
# Sync execution (bridge / agent.execute)
# ---------------------------------------------------------------------------

def run_sync(task: str, mode: str = "SMART", max_steps: int = 60) -> Dict[str, Any]:
    started = time.time()
    logger.info(f"Agent started (sync): [{mode}] {task[:120]}")
    ctx = gather_context()
    plan = build_plan(task, mode=mode, context=ctx, max_steps=max_steps)
    steps = plan["steps"]
    results: List[Dict[str, Any]] = []
    _set_progress(0, len(steps), "Planning task...", "RUNNING")
    for i, step in enumerate(steps):
        _set_progress(i, len(steps), f"{step.get('label')}...")
        record = run_step(step, ctx)
        results.append(record)
        if record["status"] == "FAILED" and step.get("critical"):
            logger.error(f"Critical step failed — aborting: {step.get('label')}")
            break
    failed = sum(1 for r in results if r["status"] == "FAILED")
    summary = {"task": task, "mode": mode,
               "total": len(steps), "done": len(results),
               "failed": failed,
               "skipped": sum(1 for r in results if r["status"] == "SKIPPED"),
               "results": results,
               "duration_ms": int((time.time() - started) * 1000)}
    _set_progress(len(results), len(steps),
                  "Task completed." if failed == 0 else f"Done with {failed} failure(s).",
                  "DONE" if failed == 0 else "ERROR")
    props = _props()
    if props is not None:
        try:
            props.agent_summary = (f"[{mode}] {task[:80]} — "
                                   f"{len(results) - failed}/{len(steps)} steps OK, "
                                   f"{failed} failed.")
        except (AttributeError, RuntimeError, TypeError):
            pass
    logger.info(f"Agent finished (sync): {len(results) - failed}/{len(steps)} OK.")
    return summary


# ---------------------------------------------------------------------------
# Async execution (START AGENT button — non-blocking timer)
# ---------------------------------------------------------------------------

def start_async(task: str, mode: str = "SMART") -> tuple:
    global _JOB, _TIMER_REGISTERED
    if _JOB is not None and _JOB.get("status") == "RUNNING":
        return False, "Agent is already running."
    try:
        import bpy  # type: ignore
    except ImportError:
        return False, "Async agent needs Blender."
    try:
        prefs = bpy.context.preferences.addons.get("blender_ai_connection")
        max_steps = int(getattr(prefs.preferences, "max_steps", 60)) if prefs else 60
    except (AttributeError, ValueError, RuntimeError):
        max_steps = 60
    try:
        ctx = gather_context()
        plan = build_plan(task, mode=mode, context=ctx, max_steps=max_steps)
    except ValueError as exc:
        return False, str(exc)
    _JOB = {"task": task, "mode": mode, "plan": plan, "index": 0,
            "results": [], "ctx": ctx, "status": "RUNNING",
            "cancel_requested": False, "started": time.time()}
    props = _props()
    if props is not None:
        try:
            props.history.clear()
            props.agent_summary = ""
        except (AttributeError, RuntimeError, TypeError):
            pass
    _set_progress(0, len(plan["steps"]), "Agent started...", "RUNNING")
    logger.info(f"Agent started: [{mode}] {task[:120]} ({len(plan['steps'])} steps)")
    for note in plan.get("notes", []):
        logger.info(f"Plan note: {note}")
    if not _TIMER_REGISTERED:
        try:
            bpy.app.timers.register(_agent_tick, first_interval=_TICK_INTERVAL)
            _TIMER_REGISTERED = True
        except (AttributeError, RuntimeError, ValueError) as exc:
            _JOB = None
            return False, f"Could not start agent timer: {exc}"
    return True, f"Agent started — {len(plan['steps'])} steps ({mode})."


def _agent_tick():
    global _JOB, _TIMER_REGISTERED
    job = _JOB
    if job is None or job.get("status") != "RUNNING":
        _TIMER_REGISTERED = False
        return None
    if job.get("cancel_requested"):
        _finalize(job, "CANCELLED")
        _TIMER_REGISTERED = False
        return None
    steps = job["plan"]["steps"]
    idx = job["index"]
    if idx >= len(steps):
        _finalize(job, "DONE")
        _TIMER_REGISTERED = False
        return None
    step = steps[idx]
    _set_progress(idx, len(steps), f"{step.get('label')}...")
    try:
        record = run_step(step, job["ctx"])
    except Exception as exc:  # noqa: BLE001 - one bad step must not kill the timer
        logger.error(f"Executor exception: {exc}\n{traceback.format_exc(limit=3)}")
        record = {"seq": step.get("seq"), "tool": step.get("tool"),
                  "label": step.get("label"), "status": "FAILED",
                  "message": str(exc), "duration_ms": 0}
    job["results"].append(record)
    job["index"] += 1
    if record["status"] == "FAILED" and step.get("critical"):
        logger.error(f"Critical step failed — aborting: {step.get('label')}")
        _finalize(job, "ERROR")
        _TIMER_REGISTERED = False
        return None
    if job["index"] >= len(steps):
        failed = sum(1 for r in job["results"] if r["status"] == "FAILED")
        _finalize(job, "DONE" if failed == 0 else "ERROR")
        _TIMER_REGISTERED = False
        return None
    return _TICK_INTERVAL


def _finalize(job: Dict[str, Any], status: str) -> None:
    job["status"] = status
    results = job["results"]
    failed = sum(1 for r in results if r["status"] == "FAILED")
    total = len(job["plan"]["steps"])
    ms = int((time.time() - job["started"]) * 1000)
    if status == "CANCELLED":
        current, summary = "Cancelled by user.", f"Cancelled after {len(results)} steps."
    elif failed == 0:
        current = "Task completed."
        summary = (f"[{job['mode']}] {job['task'][:80]} — "
                   f"{len(results)}/{total} steps OK ({ms // 1000}s).")
    else:
        current = f"Done with {failed} failure(s)."
        summary = (f"[{job['mode']}] {job['task'][:80]} — "
                   f"{len(results) - failed}/{total} OK, {failed} failed.")
    _set_progress(len(results), total, current, status)
    props = _props()
    if props is not None:
        try:
            props.agent_summary = summary
        except (AttributeError, RuntimeError, TypeError):
            pass
    logger.info(f"Agent {status.lower()}: {summary}")


def cancel() -> None:
    job = _JOB
    if job is not None and job.get("status") == "RUNNING":
        job["cancel_requested"] = True
        logger.info("Agent cancellation requested.")
    try:
        from .llm_runner import cancel_llm
        cancel_llm()
    except (ImportError, AttributeError, RuntimeError):
        pass


def shutdown_timer() -> None:
    global _JOB, _TIMER_REGISTERED
    if _JOB is not None:
        _JOB["status"] = "CANCELLED"
        _JOB = None
    if _TIMER_REGISTERED:
        try:
            import bpy  # type: ignore
            try:
                bpy.app.timers.unregister(_agent_tick)
            except ValueError:
                pass
        except ImportError:
            pass
        _TIMER_REGISTERED = False
