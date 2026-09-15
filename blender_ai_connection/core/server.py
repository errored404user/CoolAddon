"""TCP bridge server: Blender <-> MCP / agent-runner communication.

Design (Blender-safe):
- Network I/O happens on background threads (socketserver).
- bpy work happens ONLY on the main thread via a ``bpy.app.timers`` callback
  that drains a queue of pending requests and routes them to the dispatcher.

Protocol: newline-delimited JSON, see :mod:`core.protocol`.
"""

from __future__ import annotations

import json
import queue
import socketserver
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from . import dispatcher, logger
from .protocol import make_error, make_response, parse_request

MAX_LINE_BYTES = 10 * 1024 * 1024  # 10 MB guard against malformed floods
DRAIN_PER_TICK = 10
TIMER_INTERVAL = 0.1

_request_queue: "queue.Queue[Tuple[Dict[str, Any], queue.Queue]]" = queue.Queue()

_stats: Dict[str, Any] = {
    "running": False,
    "host": "127.0.0.1",
    "port": 9876,
    "started_at": None,
    "requests_total": 0,
    "errors_total": 0,
    "last_request_at": None,
    "last_tool": None,
    "last_mcp_ping": None,
}

_server: Optional[socketserver.TCPServer] = None
_thread: Optional[threading.Thread] = None
_timer_active = False


# ---------------------------------------------------------------------------
# Socket layer (background threads — NEVER touch bpy here)
# ---------------------------------------------------------------------------

class _Handler(socketserver.StreamRequestHandler):
    timeout = 300

    def handle(self):
        peer = f"{self.client_address[0]}:{self.client_address[1]}"
        logger.debug(f"Bridge client connected: {peer}")
        try:
            while True:
                raw = self.rfile.readline(MAX_LINE_BYTES + 2)
                if not raw:
                    break
                if len(raw) > MAX_LINE_BYTES + 1:
                    self._send(make_response(
                        "0", False, None,
                        make_error("INVALID_REQUEST", "Request line exceeds size limit.")))
                    break
                try:
                    text = raw.decode("utf-8", errors="replace").strip()
                except (ValueError, UnicodeError):
                    continue
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except ValueError:
                    self._send(make_response(
                        "0", False, None,
                        make_error("INVALID_REQUEST", "Request is not valid JSON.")))
                    continue
                request, perr = parse_request(data)
                if perr:
                    rid = data.get("id", "0") if isinstance(data, dict) else "0"
                    self._send(make_response(rid, False, None, perr))
                    continue
                reply: queue.Queue = queue.Queue()
                _request_queue.put((request, reply))
                try:
                    response = reply.get(timeout=request["timeout"] + 10)
                except queue.Empty:
                    response = make_response(
                        request["id"], False, None,
                        make_error("TIMEOUT", "Blender did not answer in time "
                                              "(is the main thread blocked?)."))
                self._send(response)
        except (ConnectionError, BrokenPipeError, ValueError, OSError) as exc:
            logger.debug(f"Bridge client {peer} disconnected: {exc}")
        except Exception as exc:  # noqa: BLE001 - handler must never kill server
            logger.error(f"Bridge handler error: {exc}")

    def _send(self, response: Dict[str, Any]) -> None:
        payload = (json.dumps(response, default=str) + "\n").encode("utf-8")
        self.wfile.write(payload)
        self.wfile.flush()


class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------------------
# Main-thread pump (bpy work happens here)
# ---------------------------------------------------------------------------

def process_queue():
    """Timer callback: execute pending requests via the dispatcher.

    Returns the reschedule interval while the server runs, else None.
    Safe to call manually in tests (dispatcher handles missing bpy).
    """
    drained = 0
    while drained < DRAIN_PER_TICK:
        try:
            request, reply = _request_queue.get_nowait()
        except queue.Empty:
            break
        drained += 1
        _stats["requests_total"] += 1
        _stats["last_request_at"] = datetime.now().strftime("%H:%M:%S")
        _stats["last_tool"] = request.get("tool")
        try:
            response = dispatcher.dispatch(request)
        except Exception as exc:  # noqa: BLE001 - absolute safety net
            logger.error(f"process_queue safety net: {exc}")
            response = make_response(
                request.get("id", "0"), False, None,
                make_error("INTERNAL_ERROR", str(exc)))
        if not response.get("ok"):
            _stats["errors_total"] += 1
        try:
            reply.put_nowait(response)
        except queue.Full:
            pass
    if _server is None:
        return None
    return TIMER_INTERVAL


def note_mcp_heartbeat() -> None:
    _stats["last_mcp_ping"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_stats() -> Dict[str, Any]:
    stats = dict(_stats)
    stats["queued"] = _request_queue.qsize()
    return stats


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def is_running() -> bool:
    return _server is not None


def start(host: str = "127.0.0.1", port: int = 9876) -> Tuple[bool, str]:
    global _server, _thread, _timer_active
    if _server is not None:
        return True, f"Bridge already running on {_stats['host']}:{_stats['port']}."
    try:
        server = _ThreadedTCPServer((host, int(port)), _Handler)
    except OSError as exc:
        return False, f"Could not bind {host}:{port} — {exc}."
    _server = server
    _stats.update({"running": True, "host": host, "port": int(port),
                   "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    _thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                               name="BlenderAIBridge", daemon=True)
    _thread.start()
    # Register the main-thread pump (Blender only).
    try:
        import bpy  # type: ignore

        if not _timer_active:
            bpy.app.timers.register(process_queue, first_interval=TIMER_INTERVAL,
                                    persistent=True)
            _timer_active = True
    except ImportError:
        pass  # tests / headless: caller pumps process_queue() manually
    except (AttributeError, RuntimeError, ValueError) as exc:
        logger.warning(f"Bridge timer registration issue: {exc}")
    logger.info(f"Bridge listening on {host}:{port}.")
    return True, f"Bridge listening on {host}:{port}."


def stop() -> Tuple[bool, str]:
    global _server, _thread, _timer_active
    if _server is None:
        return True, "Bridge was not running."
    server, _server = _server, None
    try:
        server.shutdown()
        server.server_close()
    except OSError as exc:
        logger.warning(f"Bridge shutdown note: {exc}")
    if _thread is not None:
        _thread.join(timeout=2.0)
        _thread = None
    try:
        import bpy  # type: ignore

        if _timer_active:
            try:
                bpy.app.timers.unregister(process_queue)
            except ValueError:
                pass
            _timer_active = False
    except ImportError:
        pass
    # Drain stale queue so a restart begins clean.
    while True:
        try:
            _request_queue.get_nowait()
        except queue.Empty:
            break
    _stats["running"] = False
    logger.info("Bridge stopped.")
    return True, "Bridge stopped."


def pump_once_for_tests(max_requests: int = 50) -> int:
    """Test helper: run dispatcher over queued requests without Blender timers."""
    done = 0
    while done < max_requests:
        try:
            request, reply = _request_queue.get_nowait()
        except queue.Empty:
            break
        try:
            reply.put_nowait(dispatcher.dispatch(request))
        except queue.Full:
            pass
        done += 1
    # keep timer semantics for callers that use process_queue directly
    if _server is None:
        process_queue()
    return done
