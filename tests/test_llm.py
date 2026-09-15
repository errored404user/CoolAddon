"""LLM layer tests: providers, format converters, agent loop (no network)."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blender_ai_connection.llm import agent_loop  # noqa: E402
from blender_ai_connection.llm import client as llm_client  # noqa: E402
from blender_ai_connection.llm import providers as llm_providers  # noqa: E402
from blender_ai_connection.llm.providers import LlmError, resolve_config  # noqa: E402
from blender_ai_connection.llm.schema import (  # noqa: E402
    anthropic_tools,
    gemini_tools,
    openai_tools,
    to_json_schema,
)

MANIFEST = [
    {"id": "scene.inspect", "description": "Inspect.",
     "params": {"object_limit": {"type": "int", "default": 200}}},
    {"id": "modeling.create_primitive",
     "description": "Create.",
     "params": {"kind": {"type": "string", "default": "CUBE",
                         "choices": ["CUBE", "SPHERE_UV"]},
                "name": {"type": "string", "required": True}}},
]


class TestProviders(unittest.TestCase):
    def test_list_six(self):
        ids = {p["id"] for p in llm_providers.list_providers()}
        self.assertEqual(ids, {"openai", "deepseek", "gemini", "moonshot",
                               "anthropic", "custom"})

    def test_resolve_defaults(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            cfg = resolve_config("openai")
        self.assertEqual((cfg["format"], cfg["base_url"], cfg["model"]),
                         ("openai", "https://api.openai.com/v1", "gpt-4o-mini"))

    def test_resolve_overrides(self):
        cfg = resolve_config("custom", model="m", api_key="",
                             base_url="https://gpt.crax.lol/v1")
        self.assertEqual(cfg["base_url"], "https://gpt.crax.lol/v1")
        self.assertEqual(cfg["model"], "m")

    def test_missing_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LlmError) as ctx:
                resolve_config("deepseek")
        self.assertEqual(ctx.exception.code, "MISSING_KEY")

    def test_custom_key_optional(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = resolve_config("custom", model="m",
                                 base_url="http://localhost:11434/v1")
        self.assertEqual(cfg["api_key"], "")

    def test_unknown_provider(self):
        with self.assertRaises(LlmError):
            resolve_config("copilot")


class TestSchema(unittest.TestCase):
    def test_json_schema(self):
        schema = to_json_schema(MANIFEST[1]["params"])
        self.assertEqual(schema["required"], ["name"])
        self.assertEqual(schema["properties"]["kind"]["enum"],
                         ["CUBE", "SPHERE_UV"])

    def test_provider_wrappers(self):
        self.assertEqual(openai_tools(MANIFEST)[0]["type"], "function")
        self.assertIn("input_schema", anthropic_tools(MANIFEST)[0])
        self.assertIn("function_declarations", gemini_tools(MANIFEST)[0])


class TestClientFormats(unittest.TestCase):
    cfg_openai = {"format": "openai", "base_url": "http://x/v1",
                  "model": "m", "api_key": "k"}

    def test_openai_roundtrip(self):
        messages = [
            {"role": "system", "text": "sys"},
            {"role": "user", "text": "hi"},
            {"role": "assistant", "text": "doing",
             "tool_calls": [{"id": "c1", "name": "scene.inspect",
                             "args": {"object_limit": 5}}]},
            {"role": "tool", "text": "OK", "tool_call_id": "c1",
             "tool_name": "scene.inspect"},
        ]
        payload = llm_client.build_openai_payload(self.cfg_openai, messages,
                                                 MANIFEST)
        self.assertEqual(payload["messages"][3]["tool_call_id"], "c1")
        self.assertEqual(payload["tools"][0]["function"]["name"],
                         "scene.inspect")
        parsed = llm_client.parse_openai_response(
            {"choices": [{"message": {"content": "done", "tool_calls": [
                {"id": "c1", "function": {"name": "scene.inspect",
                                          "arguments": '{"a": 1}'}}]}}]})
        self.assertEqual(parsed["tool_calls"][0]["args"], {"a": 1})

    def test_anthropic_merges_tool_results(self):
        messages = [
            {"role": "system", "text": "sys"},
            {"role": "user", "text": "go"},
            {"role": "assistant", "text": "",
             "tool_calls": [{"id": "a", "name": "t", "args": {}},
                            {"id": "b", "name": "t", "args": {}}]},
            {"role": "tool", "text": "r1", "tool_call_id": "a",
             "tool_name": "t"},
            {"role": "tool", "text": "r2", "tool_call_id": "b",
             "tool_name": "t"},
        ]
        payload = llm_client.build_anthropic_payload(
            {"model": "m"}, messages, MANIFEST)
        users = [m for m in payload["messages"] if m["role"] == "user"]
        self.assertEqual(len(users), 2)
        self.assertEqual(len(users[1]["content"]), 2)
        parsed = llm_client.parse_anthropic_response(
            {"content": [{"type": "text", "text": "ok"},
                         {"type": "tool_use", "id": "u1",
                          "name": "scene.inspect", "input": {}}]})
        self.assertEqual((parsed["text"], parsed["tool_calls"][0]["id"]),
                         ("ok", "u1"))

    def test_gemini_function_role(self):
        messages = [
            {"role": "user", "text": "go"},
            {"role": "assistant", "text": "",
             "tool_calls": [{"id": "c0", "name": "scene.inspect",
                             "args": {}}]},
            {"role": "tool", "text": "OK", "tool_call_id": "c0",
             "tool_name": "scene.inspect"},
        ]
        payload = llm_client.build_gemini_payload({"model": "m"}, messages,
                                                  MANIFEST)
        fn_msg = [c for c in payload["contents"] if c["role"] == "function"]
        self.assertEqual(len(fn_msg), 1)
        self.assertEqual(fn_msg[0]["parts"][0]["functionResponse"]["name"],
                         "scene.inspect")
        parsed = llm_client.parse_gemini_response(
            {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "scene.inspect", "args": {}}}]}}]})
        self.assertEqual(parsed["tool_calls"][0]["name"], "scene.inspect")


class TestAgentLoop(unittest.TestCase):
    def _script(self, replies):
        state = {"i": 0}

        def chat_fn(_messages, _manifest):
            reply = replies[min(state["i"], len(replies) - 1)]
            state["i"] += 1
            return reply

        return chat_fn

    def test_happy_path(self):
        seen = []

        def exec_fn(tool, args):
            seen.append(tool)
            if tool == "scene.inspect":
                return {"ok": True, "result": {"scene": "S", "objects_total": 1,
                                               "objects_by_type": {"MESH": 1},
                                               "objects": [{"name": "Cube",
                                                            "type": "MESH"}]}}
            return {"ok": True, "result": {"name": "Cube"}}

        outcome = agent_loop.run_loop(
            "make a cube", manifest=MANIFEST,
            chat_fn=self._script([
                {"text": "on it", "tool_calls": [
                    {"id": "1", "name": "modeling.create_primitive",
                     "args": {"name": "Cube"}}]},
                {"text": "done", "tool_calls": []}]),
            exec_fn=exec_fn)
        self.assertEqual(outcome["stopped"], "done")
        self.assertEqual(outcome["final"], "done")
        self.assertEqual(seen, ["scene.inspect", "modeling.create_primitive"])

    def test_denied_and_unknown_blocked(self):
        seen = []

        def exec_fn(tool, _args):
            seen.append(tool)
            return {"ok": True, "result": {}}

        outcome = agent_loop.run_loop(
            "x", manifest=MANIFEST, denied=["scene.inspect"],
            chat_fn=self._script([
                {"text": "", "tool_calls": [
                    {"id": "1", "name": "scene.inspect", "args": {}},
                    {"id": "2", "name": "hal.hallucinate", "args": {}}]},
                {"text": "understood", "tool_calls": []}]),
            exec_fn=exec_fn)
        # scene.inspect IS executed once for the turn-0 context (not via LLM),
        # but never for the denied LLM call; unknown tool never executes.
        self.assertEqual(seen, ["scene.inspect"])
        self.assertEqual(outcome["tool_errors"], 2)

    def test_max_iters(self):
        outcome = agent_loop.run_loop(
            "x", manifest=MANIFEST, max_iters=3,
            chat_fn=self._script([{"text": "", "tool_calls": [
                {"id": "1", "name": "scene.inspect", "args": {}}]}]),
            exec_fn=lambda t, a: {"ok": True, "result": {}})
        self.assertEqual((outcome["stopped"], outcome["turns"]),
                         ("max_iters", 3))

    def test_abort(self):
        def exec_fn(_t, _a):
            raise agent_loop.LoopAbort()

        outcome = agent_loop.run_loop(
            "x", manifest=MANIFEST,
            chat_fn=self._script([{"text": "done", "tool_calls": []}]),
            exec_fn=exec_fn)
        self.assertEqual(outcome["stopped"], "aborted")

    def test_llm_error(self):
        def chat_fn(_m, _t):
            raise LlmError("AUTH", "bad key")

        outcome = agent_loop.run_loop(
            "x", manifest=MANIFEST, chat_fn=chat_fn,
            exec_fn=lambda t, a: {"ok": True, "result": {}})
        self.assertEqual(outcome["stopped"], "error")
        self.assertIn("AUTH", outcome["final"])

    def test_manifest_excludes_agent(self):
        manifest = agent_loop.llm_manifest()
        ids = {t["id"] for t in manifest}
        self.assertNotIn("agent.execute", ids)
        self.assertIn("system.tools", ids)
        self.assertGreater(len(manifest), 80)


if __name__ == "__main__":
    unittest.main()
