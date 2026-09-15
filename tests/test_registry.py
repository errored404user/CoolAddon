"""Tool registry tests: every tool importable + validated without Blender."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blender_ai_connection.tools import (  # noqa: E402
    TOOL_CATEGORIES,
    TOOL_REGISTRY,
    get_tool,
    list_tools,
    tools_manifest,
    validate_params,
)


class TestRegistry(unittest.TestCase):
    def test_registry_populated(self):
        self.assertGreaterEqual(len(TOOL_REGISTRY), 80,
                                f"only {len(TOOL_REGISTRY)} tools registered")

    def test_ids_and_categories(self):
        valid = {c for c, _ in TOOL_CATEGORIES}
        for tool_id, tool in TOOL_REGISTRY.items():
            self.assertIn(".", tool_id, tool_id)
            self.assertIn(tool["category"], valid, tool_id)
            self.assertTrue(tool["label"], tool_id)
            self.assertTrue(callable(tool["func"]), tool_id)
            self.assertIsInstance(tool["params"], dict, tool_id)

    def test_expected_tools_exist(self):
        for tool_id in ("scene.inspect", "modeling.create_primitive",
                        "material.create", "animation.animate_transform",
                        "camera.create_sequence", "lighting.setup_preset",
                        "rendering.render", "nodes.create_geonodes",
                        "physics.add_rigid_body", "project.export",
                        "character.build_simple_humanoid",
                        "environment.create_preset",
                        "procedural.create_building",
                        "optimization.analyze", "debug.diagnose",
                        "cutscene.build_sequence", "agent.execute"):
            if tool_id == "agent.execute":
                continue  # system tool, not in registry
            self.assertIsNotNone(get_tool(tool_id), tool_id)

    def test_unknown_tool(self):
        self.assertIsNone(get_tool("nope.nope"))

    def test_list_filter(self):
        modeling = list_tools("modeling")
        self.assertTrue(modeling)
        self.assertTrue(all(t["category"] == "modeling" for t in modeling))

    def test_manifest_json_serializable(self):
        manifest = tools_manifest()
        text = json.dumps(manifest)
        self.assertGreater(len(text), 1000)
        self.assertNotIn("func", text)

    def test_validate_required(self):
        cleaned, err = validate_params({}, {"name": {"type": "string",
                                                     "required": True}})
        self.assertIsNotNone(err)
        cleaned, err = validate_params({"name": "x"},
                                       {"name": {"type": "string",
                                                 "required": True}})
        self.assertIsNone(err)

    def test_validate_coercion_and_defaults(self):
        spec = {"count": {"type": "int", "default": 5},
                "ratio": {"type": "float", "default": 0.5},
                "flag": {"type": "bool", "default": False},
                "tags": {"type": "list", "default": []}}
        cleaned, err = validate_params({"count": 3.0, "flag": "yes"}, spec)
        self.assertIsNone(err)
        self.assertEqual((cleaned["count"], cleaned["ratio"], cleaned["flag"]),
                         (3, 0.5, True))

    def test_validate_choices(self):
        spec = {"kind": {"type": "string", "default": "A",
                         "choices": ["A", "B"]}}
        _, err = validate_params({"kind": "Z"}, spec)
        self.assertIsNotNone(err)
        _, err = validate_params({"kind": "B"}, spec)
        self.assertIsNone(err)


if __name__ == "__main__":
    unittest.main()
