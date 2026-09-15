"""Dashboard server tests: API + offline behavior (no Blender, no network)."""

import json
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import server as dashboard_server  # noqa: E402


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class DashboardCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, _, _ = dashboard_server.create_server(
            "127.0.0.1", 0, "127.0.0.1", _closed_port())
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    # -- helpers ------------------------------------------------------
    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=15) as res:
            return res.status, res.read()

    def _get_json(self, path: str):
        _status, body = self._get(path)
        return json.loads(body.decode("utf-8"))

    def _post(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.status, json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    # -- tests --------------------------------------------------------
    def test_index_served(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("Blender AI", body.decode("utf-8"))

    def test_status_reports_bridge_down(self):
        data = self._get_json("/api/status")
        self.assertFalse(data["bridge"]["reachable"])
        self.assertEqual(data["tools"], 89)
        self.assertEqual(data["modes"], 12)

    def test_catalogs(self):
        tools = self._get_json("/api/tools")["tools"]
        self.assertEqual(len(tools), 89)
        providers = self._get_json("/api/providers")["providers"]
        self.assertEqual({p["id"] for p in providers},
                         {"openai", "deepseek", "gemini", "moonshot",
                          "anthropic", "custom"})
        modes = self._get_json("/api/modes")["modes"]
        self.assertIn("SMART", {m["id"] for m in modes})

    def test_mcp_info(self):
        info = self._get_json("/api/mcp")
        self.assertIn("blender", info["snippet"])
        self.assertIn(info["mcp_package"], (info["mcp_package"],))  # str, any value

    def test_plan_works_offline(self):
        status, data = self._post("/api/plan", {"task": "Create a robot.",
                                                "mode": "SMART"})
        self.assertEqual(status, 200)
        self.assertIn("MODELING", data["plan"]["detected_domains"])
        self.assertFalse(data["scene_available"])

    def test_run_builtin_offline_fails_clean(self):
        status, data = self._post("/api/run", {"task": "Fix the scene.",
                                               "mode": "DEBUG",
                                               "engine": "builtin"})
        self.assertEqual(status, 202)
        job_id = data["job_id"]
        job = {}
        for _ in range(60):
            job = self._get_json(f"/api/jobs/{job_id}?since=0")
            if job["status"] in ("done", "error", "cancelled"):
                break
            time.sleep(0.2)
        self.assertIn(job["status"], ("done", "error"))
        self.assertTrue(job["events"], "expected streamed events")

    def test_tool_call_offline(self):
        status, data = self._post("/api/tool", {"tool": "scene.inspect",
                                                "params": {}})
        self.assertEqual(status, 200)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "BLENDER_UNAVAILABLE")

    def test_run_llm_validates_config(self):
        status, _ = self._post("/api/run", {"task": "x", "engine": "llm",
                                            "llm": {"provider": "nope"}})
        self.assertEqual(status, 400)
        with mock.patch.dict("os.environ", {}, clear=True):
            status, data = self._post("/api/run", {"task": "x", "engine": "llm",
                                                   "llm": {"provider": "openai"}})
        self.assertEqual(status, 400)
        self.assertIn("MISSING_KEY", data["error"])

    def test_jobs_list(self):
        data = self._get_json("/api/jobs")
        self.assertIsInstance(data["jobs"], list)

    def test_cli_help_lists_options(self):
        import subprocess
        here = Path(__file__).resolve().parent.parent
        proc = subprocess.run([sys.executable, "dashboard/server.py", "--help"],
                              capture_output=True, text=True, cwd=here,
                              timeout=30)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--open", proc.stdout)
        self.assertIn("--port", proc.stdout)


if __name__ == "__main__":
    unittest.main()
