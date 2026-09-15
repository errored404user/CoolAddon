#!/usr/bin/env python3
"""Blender AI Dashboard — web control center connecting Blender + AI providers.

NOTE: this is NOT a browser extension and NOT a Blender add-on. It is a local
web app: run it with Python, then open the printed URL in any browser.

One local dashboard (stdlib only, no installs) that:
  - connects to the Blender bridge (connection status, tools, modes),
  - runs tasks with the built-in planner OR a real LLM
    (OpenAI / DeepSeek / Gemini / Kimi / Claude / custom proxy),
  - streams execution progress, results and logs (START AGENT for the browser).

Run:
    python dashboard/server.py [--port 8899] [--blender-port 9876]
Then open http://localhost:8899
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp_server"))

from blender_client import BlenderClient, BlenderError  # noqa: E402
from blender_ai_connection.agent.planner import build_plan  # noqa: E402
from blender_ai_connection.agent.recovery import suggest_fix  # noqa: E402
from blender_ai_connection.llm import (  # noqa: E402
    LlmError,
    LoopAbort,
    llm_manifest,
    resolve_config,
    run_loop,
)
from blender_ai_connection.llm.client import chat  # noqa: E402
from blender_ai_connection.modes import modes_manifest  # noqa: E402
from blender_ai_connection.tools import tools_manifest  # noqa: E402

UI_DIR = HERE / "ui"
MAX_BODY = 10 * 1024 * 1024


def _log(message: str) -> None:
    print(f"[dashboard] {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Job store (thread-safe, in-memory)
# ---------------------------------------------------------------------------

class JobStore:
    def __init__(self, limit: int = 20):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._limit = limit

    def create(self, task: str, mode: str, engine: str,
               extra: Dict[str, Any] = None) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            job_id = f"job-{self._seq:03d}"
            job = {"id": job_id, "task": task, "mode": mode,
                   "engine": engine, "extra": extra or {},
                   "status": "queued", "progress": {"done": 0, "total": 0},
                   "current": "Queued…", "final": "", "failed": 0,
                   "events": [], "cancel_requested": False,
                   "started": time.time(), "ended": None}
            self._jobs[job_id] = job
            self._order.append(job_id)
            while len(self._order) > self._limit:
                self._jobs.pop(self._order.pop(0), None)
            return job

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._summary(self._jobs[j]) for j in reversed(self._order)]

    @staticmethod
    def _summary(job: Dict[str, Any]) -> Dict[str, Any]:
        return {k: job[k] for k in
                ("id", "task", "mode", "engine", "status", "progress",
                 "current", "final", "failed", "started", "ended")}

    def event(self, job: Dict[str, Any], kind: str, text: str) -> None:
        with self._lock:
            events = job["events"]
            events.append({"seq": len(events) + 1, "t": time.strftime("%H:%M:%S"),
                           "kind": kind, "text": (text or "")[:1500]})
            del events[:-500]

    def set(self, job: Dict[str, Any], **fields) -> None:
        with self._lock:
            job.update(fields)


# ---------------------------------------------------------------------------
# Bridge helpers
# ---------------------------------------------------------------------------

def _client(settings: Dict[str, Any]) -> BlenderClient:
    blender = settings.get("blender", {})
    return BlenderClient(blender.get("host", "127.0.0.1"),
                         int(blender.get("port", 9876)))


def _ping_bridge(settings: Dict[str, Any]) -> Dict[str, Any]:
    try:
        pong = _client(settings).ping()
        return {"reachable": True, "blender": pong.get("blender"),
                "agent": pong.get("agent"),
                "target": f"{settings['blender']['host']}:{settings['blender']['port']}"}
    except BlenderError as exc:
        return {"reachable": False, "error": exc.message,
                "target": f"{settings['blender'].get('host')}:{settings['blender'].get('port')}"}


class _Unresolved(Exception):
    pass


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
        found = first_of("MESH")
        if found:
            return found
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
        if objects and isinstance(objects[0], dict) and objects[0].get("name"):
            return objects[0]["name"]
    raise _Unresolved(f"Could not resolve {ref}: no matching object in scene.")


def _resolve(value: Any, ctx: Dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _lookup_ref(value, ctx)
    if isinstance(value, list):
        return [_resolve(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, ctx) for k, v in value.items()}
    return value


def _needs_ctx(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("$")
    if isinstance(value, list):
        return any(_needs_ctx(v) for v in value)
    if isinstance(value, dict):
        return any(_needs_ctx(v) for v in value.values())
    return False


# ---------------------------------------------------------------------------
# Runners (background threads)
# ---------------------------------------------------------------------------

def run_builtin_job(store: JobStore, settings: Dict[str, Any],
                    job: Dict[str, Any]) -> None:
    client = _client(settings)
    task, mode = job["task"], job["mode"]

    def ev(kind: str, text: str):
        store.event(job, kind, text)

    store.set(job, status="running", current="Checking Blender connection…")
    ping = _ping_bridge(settings)
    if not ping["reachable"]:
        store.set(job, status="error", current="Blender unreachable.",
                  final=ping["error"], ended=time.time())
        ev("error", ping["error"])
        return

    try:
        ctx = client.call("scene.inspect", {"object_limit": 200}, timeout=30)
    except BlenderError as exc:
        ctx = {}
        ev("warn", f"Scene context unavailable: {exc.message}")
    try:
        plan = build_plan(task, mode=mode, context=ctx or None, max_steps=60)
    except ValueError as exc:
        store.set(job, status="error", current="Planning failed.",
                  final=str(exc), ended=time.time())
        ev("error", str(exc))
        return
    steps = plan["steps"]
    store.set(job, progress={"done": 0, "total": len(steps)})
    ev("info", f"Plan: {len(steps)} steps [{mode}] "
               f"({', '.join(plan.get('detected_domains', [])) or 'inspect'})")
    for note in plan.get("notes", []):
        ev("info", f"Note: {note}")

    failed = 0
    for i, step in enumerate(steps):
        if job.get("cancel_requested"):
            break
        label = step.get("label") or step.get("tool")
        store.set(job, current=f"{label}…",
                  progress={"done": i, "total": len(steps)})
        params = dict(step.get("params") or {})
        if _needs_ctx(params):
            try:
                fresh = client.call("scene.inspect", {"object_limit": 400},
                                    timeout=30)
                if fresh:
                    ctx = fresh
            except BlenderError:
                pass
        try:
            params = _resolve(params, ctx)
        except _Unresolved as exc:
            failed += 1
            ev("skip", f"SKIP {label}: {exc}")
            continue
        outcome = _call_with_recovery(client, step.get("tool", ""), params, ctx)
        if outcome["ok"]:
            ev("ok", f"OK {label}: {outcome['summary']}")
            if step.get("tool") == "scene.inspect" and isinstance(outcome.get("result"), dict):
                ctx = outcome["result"]
        else:
            failed += 1
            ev("fail", f"FAIL {label}: {outcome['summary']}")
            if step.get("critical"):
                ev("error", "Critical step failed — aborting.")
                break
    store.set(job, progress={"done": len(steps), "total": len(steps)})
    if job.get("cancel_requested"):
        store.set(job, status="cancelled", current="Cancelled.",
                  final=f"Cancelled. {failed} failure(s).", failed=failed,
                  ended=time.time())
    else:
        ok = failed == 0
        store.set(job, status="done" if ok else "done",
                  current="Task completed." if ok else f"Done with {failed} failure(s).",
                  final=f"{len(steps) - failed}/{len(steps)} steps OK, {failed} failed.",
                  failed=failed, ended=time.time())
    ev("done", job["final"])


def _call_with_recovery(client: BlenderClient, tool: str,
                        params: Dict[str, Any],
                        ctx: Dict[str, Any]) -> Dict[str, Any]:
    last_summary, last_result = "", None
    for attempt in (1, 2):
        try:
            result = client.call(tool, params, timeout=600)
            return {"ok": True, "result": result,
                    "summary": _short(result) + (" (retried)" if attempt > 1 else "")}
        except BlenderError as exc:
            last_summary = f"[{exc.code}] {exc.message}"
            if attempt == 1:
                fix = suggest_fix(tool, params,
                                  {"code": exc.code, "message": exc.message,
                                   "details": exc.details}, ctx)
                if fix:
                    params = fix["params"]
                    last_summary += f" — retrying ({fix['note']})"
                    continue
            return {"ok": False, "result": last_result, "summary": last_summary}
    return {"ok": False, "result": None, "summary": last_summary}


def _short(result: Any, cap: int = 220) -> str:
    if result is None:
        return "ok"
    try:
        return json.dumps(result, default=str)[:cap]
    except (TypeError, ValueError):
        return "ok"


def run_llm_job(store: JobStore, settings: Dict[str, Any],
                job: Dict[str, Any], llm: Dict[str, Any]) -> None:
    client = _client(settings)

    def ev(kind: str, text: str):
        store.event(job, kind, text)

    store.set(job, status="running", current="Checking Blender connection…")
    ping = _ping_bridge(settings)
    if not ping["reachable"]:
        store.set(job, status="error", current="Blender unreachable.",
                  final=ping["error"], ended=time.time())
        ev("error", ping["error"])
        return
    try:
        cfg = resolve_config(llm.get("provider", "openai"),
                             llm.get("model", ""), llm.get("api_key", ""),
                             llm.get("base_url", ""))
    except LlmError as exc:
        store.set(job, status="error", current="LLM config error.",
                  final=f"[{exc.code}] {exc.message}", ended=time.time())
        ev("error", f"[{exc.code}] {exc.message}")
        return
    ev("info", f"Model: {cfg['label']} / {cfg['model']}")
    manifest = llm_manifest()
    denied = list(settings.get("denied_tools", []) or [])

    def exec_fn(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if job.get("cancel_requested"):
            raise LoopAbort()
        try:
            return {"ok": True,
                    "result": client.call(tool, args or {}, timeout=600),
                    "error": None}
        except BlenderError as exc:
            return {"ok": False, "result": None,
                    "error": {"code": exc.code, "message": exc.message}}

    def on_event(kind: str, data: Any) -> None:
        if job.get("cancel_requested"):
            raise LoopAbort()
        if kind == "assistant_text":
            store.set(job, current=str(data)[:300])
            ev("model", str(data)[:800])
        elif kind == "tool_start":
            store.set(job, current=f"{data.get('name')}…")
            ev("run", f"→ {data.get('name')}")
        elif kind == "tool_result":
            ok = bool(data.get("ok"))
            store.set(job, progress={"done": job["progress"]["done"] + 1,
                                     "total": job["progress"]["done"] + 6})
            ev("ok" if ok else "fail",
               f"{'OK' if ok else 'FAIL'} {data.get('name')}: {data.get('text', '')[:300]}")
        elif kind == "error":
            ev("error", str(data))

    try:
        outcome = run_loop(job["task"], mode=job["mode"], cfg=cfg,
                           manifest=manifest,
                           chat_fn=lambda m, t: chat(cfg, m, t, timeout=180),
                           exec_fn=exec_fn,
                           max_iters=int(llm.get("max_iters", 25) or 25),
                           denied=denied, on_event=on_event)
    except LoopAbort:
        outcome = {"final": "Cancelled.", "stopped": "aborted",
                   "tool_calls": 0, "tool_errors": 0, "turns": 0}
    except Exception as exc:  # noqa: BLE001
        _log(f"LLM job crash: {exc}\n{traceback.format_exc(limit=2)}")
        outcome = {"final": f"Runner failure: {exc}", "stopped": "error",
                   "tool_calls": 0, "tool_errors": 1, "turns": 0}
    if job.get("cancel_requested") or outcome.get("stopped") == "aborted":
        store.set(job, status="cancelled", current="Cancelled.",
                  final="Cancelled.", ended=time.time())
    elif outcome.get("stopped") == "error":
        store.set(job, status="error", current="LLM run failed.",
                  final=outcome.get("final", ""), ended=time.time())
    else:
        store.set(job, status="done", current="Task completed.",
                  final=outcome.get("final", ""),
                  failed=outcome.get("tool_errors", 0), ended=time.time())
    ev("done", job["final"][:800])


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "BlenderAIDashboard/1.0"
    settings: Dict[str, Any] = {}
    store: JobStore = None  # type: ignore

    def log_message(self, fmt: str, *args) -> None:
        _log(f"{self.address_string()} {fmt % args}")

    # -- helpers ---------------------------------------------------------
    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            return {}

    def _serve_static(self, name: str) -> None:
        if name in ("", "/"):
            name = "index.html"
        target = (UI_DIR / name.lstrip("/")).resolve()
        if UI_DIR.resolve() not in target.parents and target != UI_DIR.resolve():
            return self._send_json({"error": "forbidden"}, 403)
        if not target.is_file():
            return self._send_json({"error": "not found"}, 404)
        ctype = {".html": "text/html", ".js": "text/javascript",
                 ".css": "text/css"}.get(target.suffix.lower(),
                                         "application/octet-stream")
        try:
            data = target.read_bytes()
        except OSError:
            return self._send_json({"error": "read failed"}, 500)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- GET -------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/status":
            ping = _ping_bridge(self.settings)
            return self._send_json({"bridge": ping, "tools": len(tools_manifest()),
                                    "modes": len(modes_manifest())})
        if path == "/api/providers":
            from blender_ai_connection.llm import list_providers
            return self._send_json({"providers": list_providers()})
        if path == "/api/modes":
            return self._send_json({"modes": modes_manifest()})
        if path == "/api/tools":
            return self._send_json({"tools": tools_manifest()})
        if path == "/api/mcp":
            return self._send_json(_mcp_info(self.settings))
        if path == "/api/config":
            public = {k: v for k, v in self.settings.items()
                      if k in ("blender", "defaults", "denied_tools")}
            return self._send_json(public)
        if path == "/api/jobs":
            return self._send_json({"jobs": self.store.list()})
        if path.startswith("/api/jobs/"):
            job_id = path[len("/api/jobs/"):].strip("/")
            job = self.store.get(job_id)
            if job is None:
                return self._send_json({"error": "unknown job"}, 404)
            try:
                since = int(urllib_parse_qs(parsed.query).get("since", ["0"])[0])
            except (ValueError, KeyError):
                since = 0
            with self.store._lock:
                payload = dict(job)
                payload["events"] = [e for e in job["events"]
                                     if e["seq"] > since]
            return self._send_json(payload)
        return self._serve_static(path.lstrip("/") or "index.html")

    # -- POST ------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json()
        if path == "/api/connection":
            host = str(body.get("host", "127.0.0.1")).strip() or "127.0.0.1"
            try:
                port = int(body.get("port", 9876))
            except (TypeError, ValueError):
                return self._send_json({"error": "invalid port"}, 400)
            self.settings["blender"] = {"host": host, "port": port}
            return self._send_json({"ok": True, "bridge": _ping_bridge(self.settings)})
        if path == "/api/plan":
            task = (body.get("task") or "").strip()
            mode = (body.get("mode") or "SMART").upper()
            if not task:
                return self._send_json({"error": "task is required"}, 400)
            try:
                ctx = _client(self.settings).call(
                    "scene.inspect", {"object_limit": 200}, timeout=20)
            except BlenderError:
                ctx = {}
            try:
                plan = build_plan(task, mode=mode, context=ctx or None,
                                  max_steps=60)
            except ValueError as exc:
                return self._send_json({"error": str(exc)}, 400)
            return self._send_json({"plan": plan,
                                    "scene_available": bool(ctx)})
        if path == "/api/run":
            task = (body.get("task") or "").strip()
            mode = (body.get("mode") or "SMART").upper()
            engine = (body.get("engine") or "builtin").lower()
            if not task:
                return self._send_json({"error": "task is required"}, 400)
            if engine not in ("builtin", "llm"):
                return self._send_json({"error": "engine must be builtin|llm"}, 400)
            llm_cfg = body.get("llm") if isinstance(body.get("llm"), dict) else {}
            if engine == "llm":
                try:
                    cfg = resolve_config(llm_cfg.get("provider", "openai"),
                                         llm_cfg.get("model", ""),
                                         llm_cfg.get("api_key", ""),
                                         llm_cfg.get("base_url", ""))
                    llm_cfg = {"provider": cfg["id"], "model": cfg["model"],
                               "api_key": cfg["api_key"],
                               "base_url": cfg["base_url"],
                               "max_iters": int(body.get("max_iters") or
                                                llm_cfg.get("max_iters", 25) or 25)}
                except (LlmError, ValueError) as exc:
                    code = getattr(exc, "code", "LLM_ERROR")
                    return self._send_json(
                        {"error": f"LLM config [{code}]: {exc}"}, 400)
            job = self.store.create(task, mode, engine,
                                    {"llm": {k: v for k, v in llm_cfg.items()
                                             if k != "api_key"}})
            # NOTE: the key lives only in the worker thread closure, never in
            # the stored job (jobs are served back over HTTP).
            target = (run_llm_job if engine == "llm" else run_builtin_job)
            args = (self.store, self.settings, job, llm_cfg) if engine == "llm" else (
                self.store, self.settings, job)
            threading.Thread(target=_guarded, args=(target, args, self.store, job),
                             name=f"ext-{job['id']}", daemon=True).start()
            return self._send_json({"job_id": job["id"]}, 202)
        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = path[len("/api/jobs/"):-len("/cancel")].strip("/")
            job = self.store.get(job_id)
            if job is None:
                return self._send_json({"error": "unknown job"}, 404)
            self.store.set(job, cancel_requested=True)
            return self._send_json({"ok": True})
        if path == "/api/tool":
            tool = (body.get("tool") or "").strip()
            params = body.get("params") or {}
            if not tool:
                return self._send_json({"error": "tool is required"}, 400)
            if not isinstance(params, dict):
                return self._send_json({"error": "params must be an object"}, 400)
            try:
                result = _client(self.settings).call(tool, params, timeout=300)
            except BlenderError as exc:
                return self._send_json({"ok": False, "result": None,
                                        "error": {"code": exc.code,
                                                  "message": exc.message}})
            return self._send_json({"ok": True, "result": result, "error": None})
        return self._send_json({"error": "unknown endpoint"}, 404)


def urllib_parse_qs(query: str):
    from urllib.parse import parse_qs
    return parse_qs(query)


def _guarded(target, args, store: JobStore, job: Dict[str, Any]) -> None:
    try:
        target(*args)
    except Exception as exc:  # noqa: BLE001 - background jobs must never die silent
        _log(f"job {job['id']} crash: {exc}\n{traceback.format_exc(limit=2)}")
        store.event(job, "error", f"Runner crash: {exc}")
        store.set(job, status="error", current="Runner crash.",
                  final=str(exc), ended=time.time())


def _mcp_info(settings: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import mcp  # type: ignore  # noqa: F401
        package: Optional[str] = getattr(mcp, "__version__", "installed")
    except ImportError:
        package = None
    script = ROOT / "mcp_server" / "server.py"
    blender = settings.get("blender", {})
    snippet = {"mcpServers": {"blender": {
        "command": "python",
        "args": [str(script), "--host", blender.get("host", "127.0.0.1"),
                 "--port", str(blender.get("port", 9876))],
    }}}
    return {"mcp_package": package or "missing",
            "server_script": str(script) if script.exists() else "missing",
            "snippet": json.dumps(snippet, indent=2)}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def load_config(path: Path) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "server": {"host": "0.0.0.0", "port": 8899},
        "blender": {"host": "127.0.0.1", "port": 9876},
        "defaults": {"mode": "SMART", "engine": "builtin",
                     "provider": "openai", "max_iters": 25},
        "denied_tools": [],
    }
    try:
        file_cfg = json.loads(path.read_text(encoding="utf-8"))
        for key in ("server", "blender", "defaults"):
            if isinstance(file_cfg.get(key), dict):
                defaults[key].update(file_cfg[key])
        if isinstance(file_cfg.get("denied_tools"), list):
            defaults["denied_tools"] = file_cfg["denied_tools"]
    except (OSError, ValueError) as exc:
        _log(f"config '{path}' unreadable ({exc}) — using defaults")
    return defaults


def create_server(host: str = "127.0.0.1", port: int = 0,
                  blender_host: str = "127.0.0.1",
                  blender_port: int = 9876,
                  extra: Dict[str, Any] = None):
    settings = load_config(HERE / "config" / "extension.json")
    settings["server"] = {"host": host, "port": port}
    settings["blender"] = {"host": blender_host, "port": blender_port}
    if extra:
        settings.update(extra)
    store = JobStore()
    Handler.settings = settings
    Handler.store = store
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server, settings, store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Blender AI Dashboard")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--blender-host", default=None)
    parser.add_argument("--blender-port", type=int, default=None)
    args = parser.parse_args(argv)
    settings = load_config(HERE / "config" / "extension.json")
    if args.host:
        settings["server"]["host"] = args.host
    if args.port:
        settings["server"]["port"] = args.port
    if args.blender_host:
        settings["blender"]["host"] = args.blender_host
    if args.blender_port:
        settings["blender"]["port"] = args.blender_port
    store = JobStore()
    Handler.settings = settings
    Handler.store = store
    host, port = settings["server"]["host"], int(settings["server"]["port"])
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        print(f"Could not start the dashboard on {host}:{port} ({exc}).")
        print("The port is probably already in use — retry with e.g. "
              "--port 8900, or stop the other program.")
        return 2
    server.daemon_threads = True
    url_host = "localhost" if host == "0.0.0.0" else host
    url = f"http://{url_host}:{port}"
    print(f"Blender AI Dashboard: {url}")
    print(f"Blender bridge target: {settings['blender']['host']}:{settings['blender']['port']}")
    if args.open:
        try:
            import webbrowser
            threading.Timer(0.6, webbrowser.open, args=(url,)).start()
        except Exception as exc:  # noqa: BLE001
            print(f"(Could not open a browser: {exc})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
