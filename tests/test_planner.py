"""Planner tests: task text -> sane, ordered, dependency-safe plans."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blender_ai_connection.agent.planner import build_plan  # noqa: E402
from blender_ai_connection.modes import detect_modes  # noqa: E402


def tools_of(plan):
    return [s["tool"] for s in plan["steps"]]


class TestPlanner(unittest.TestCase):
    def test_robot(self):
        plan = build_plan("Create a detailed futuristic robot.")
        self.assertIn("MODELING", plan["detected_domains"])
        tools = tools_of(plan)
        self.assertEqual(tools[0], "scene.inspect")
        self.assertIn("modeling.create_primitive", tools)
        self.assertIn("material.create", tools)
        self.assertEqual(tools[-1], "debug.diagnose")  # complex -> verified

    def test_material_targets_selection(self):
        plan = build_plan("Give the selected object a realistic metal material.",
                          mode="MATERIAL")
        self.assertEqual(plan["detected_domains"], ["MATERIAL"])
        assign = [s for s in plan["steps"] if s["tool"] == "material.assign"][0]
        self.assertTrue(assign["params"].get("use_selection"))

    def test_procedural_forest(self):
        plan = build_plan("Build a procedural forest using Geometry Nodes with 150 trees.")
        self.assertIn("PROCEDURAL", plan["detected_domains"])
        tools = tools_of(plan)
        self.assertIn("nodes.create_geonodes", tools)
        geo = [s for s in plan["steps"] if s["tool"] == "nodes.create_geonodes"][0]
        self.assertEqual(geo["params"].get("count"), 150)

    def test_cutscene_duration(self):
        plan = build_plan("Create a 30-second cinematic where a robot walks through a lab.")
        self.assertIn("CUTSCENE", plan["detected_domains"])
        seq = [s for s in plan["steps"] if s["tool"] == "cutscene.build_sequence"][0]
        shots = seq["params"]["shots"]
        self.assertEqual(len(shots), 3)
        self.assertEqual(shots[-1]["end"] - shots[0]["start"] + 1, 30 * 24)

    def test_debug(self):
        plan = build_plan("Inspect the current scene and fix any obvious problems.")
        self.assertIn("DEBUG", plan["detected_domains"])
        diag = [s for s in plan["steps"] if s["tool"] == "debug.diagnose"][0]
        self.assertTrue(diag["params"].get("auto_fix"))

    def test_optimize(self):
        plan = build_plan("Optimize this scene for better performance.")
        self.assertIn("OPTIMIZATION", plan["detected_domains"])
        self.assertIn("optimization.analyze", tools_of(plan))

    def test_smart_multidomain_order(self):
        plan = build_plan("Create a futuristic robot and make a cinematic scene "
                          "where it walks through a laboratory.")
        domains = plan["detected_domains"]
        for expected in ("MODELING", "ENVIRONMENT", "ANIMATION", "CUTSCENE"):
            self.assertIn(expected, domains)
        # Dependency order respected.
        self.assertLess(domains.index("MODELING"), domains.index("ANIMATION"))
        self.assertLess(domains.index("ANIMATION"), domains.index("CUTSCENE"))

    def test_explicit_mode_is_pure(self):
        plan = build_plan("Create a futuristic robot.", mode="LIGHTING")
        self.assertEqual(plan["detected_domains"], ["LIGHTING"])

    def test_unknown_mode_falls_back(self):
        plan = build_plan("Create a cube.", mode="NOPE")
        self.assertEqual(plan["detected_domains"], ["MODELING"])
        self.assertTrue(plan["notes"])

    def test_empty_task(self):
        with self.assertRaises(ValueError):
            build_plan("   ")

    def test_orbit_routing(self):
        self.assertIn("ANIMATION", detect_modes("orbit the object 360 degrees"))
        self.assertNotIn("CUTSCENE", detect_modes("orbit the object 360 degrees"))
        self.assertIn("CUTSCENE", detect_modes("cinematic orbit shot around the robot"))

    def test_truncation_keeps_verify_last(self):
        plan = build_plan("Create a detailed futuristic robot.", max_steps=5)
        self.assertEqual(len(plan["steps"]), 5)
        self.assertEqual(plan["steps"][-1]["tool"], "debug.diagnose")

    def test_character_routing(self):
        plan = build_plan("Create a character with a rig and wave pose.")
        self.assertIn("CHARACTER", plan["detected_domains"])
        self.assertIn("character.build_simple_humanoid", tools_of(plan))


if __name__ == "__main__":
    unittest.main()
