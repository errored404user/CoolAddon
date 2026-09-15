"""Protocol framing tests (pure python, no Blender needed)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blender_ai_connection.core.protocol import (  # noqa: E402
    make_error,
    make_response,
    parse_request,
)


class TestProtocol(unittest.TestCase):
    def test_valid_minimal(self):
        req, err = parse_request({"tool": "scene.inspect"})
        self.assertIsNone(err)
        self.assertEqual(req["tool"], "scene.inspect")
        self.assertEqual(req["params"], {})
        self.assertEqual(req["timeout"], 60)
        self.assertEqual(req["id"], "0")

    def test_valid_full(self):
        req, err = parse_request({"id": "7", "tool": "scene.delete",
                                  "params": {"pattern": "Cube*"}, "timeout": 30})
        self.assertIsNone(err)
        self.assertEqual((req["id"], req["timeout"]), ("7", 30))

    def test_timeout_clamped(self):
        req, _ = parse_request({"tool": "x", "timeout": 99999})
        self.assertEqual(req["timeout"], 1800)
        req, _ = parse_request({"tool": "x", "timeout": 0})
        self.assertEqual(req["timeout"], 1)

    def test_rejects_non_dict(self):
        _, err = parse_request(["nope"])
        self.assertEqual(err["code"], "INVALID_REQUEST")

    def test_rejects_missing_tool(self):
        _, err = parse_request({"params": {}})
        self.assertEqual(err["code"], "INVALID_REQUEST")

    def test_rejects_bad_params(self):
        _, err = parse_request({"tool": "x", "params": [1, 2]})
        self.assertEqual(err["code"], "INVALID_REQUEST")

    def test_rejects_bad_timeout(self):
        _, err = parse_request({"tool": "x", "timeout": "forever"})
        self.assertEqual(err["code"], "INVALID_REQUEST")

    def test_response_shape(self):
        ok = make_response("1", True, {"a": 1}, None, 12)
        self.assertEqual((ok["id"], ok["ok"], ok["result"], ok["error"]),
                         ("1", True, {"a": 1}, None))
        self.assertIn("protocol", ok)
        bad = make_response("2", False, None, make_error("TOOL_FAILED", "boom"))
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"]["code"], "TOOL_FAILED")

    def test_unknown_error_code_falls_back(self):
        self.assertEqual(make_error("NOPE", "x")["code"], "INTERNAL_ERROR")


if __name__ == "__main__":
    unittest.main()
