"""Heuristic task planner: natural language -> validated tool plans.

Pure Python (no bpy) and deterministic, so the built-in START AGENT path,
``agent.plan`` / ``agent.execute`` and external LLM clients can all share it.
External LLMs may also ignore plans and call tools directly — both paths run
through the same dispatcher, validation and recovery layers.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

Step = Dict[str, Any]


# ---------------------------------------------------------------------------
# Step + text helpers
# ---------------------------------------------------------------------------

def _step(tool: str, params: Optional[Dict[str, Any]] = None,
          label: str = "", critical: bool = False) -> Step:
    return {"tool": tool, "params": params or {},
            "label": label or tool, "critical": bool(critical)}


def _has(task: str, *words: str) -> bool:
    lowered = task.lower()
    return any(w in lowered for w in words)


def _extract_int(task: str, default: int, lo: int = 1, hi: int = 100000) -> int:
    match = re.search(r"(\d[\d,]*)", task)
    if not match:
        return default
    try:
        return max(lo, min(int(match.group(1).replace(",", "")), hi))
    except ValueError:
        return default


def _extract_seconds(task: str, default: int = 10) -> int:
    lowered = task.lower()
    for pattern in (r"(\d+)\s*-\s*second", r"(\d+)\s*seconds?", r"(\d+)\s*s\b"):
        match = re.search(pattern, lowered)
        if match:
            try:
                return max(1, min(int(match.group(1)), 600))
            except ValueError:
                pass
    return default


def _extract_name(task: str, default: str) -> str:
    quoted = re.search(r"""["']([\w\-\. ]{1,40})["']""", task)
    if quoted:
        return quoted.group(1).strip().replace(" ", "_")
    named = re.search(r"(?:named|called)\s+([\w\-\.]{1,40})", task, re.IGNORECASE)
    if named:
        return named.group(1).strip()
    return default


def _ctx_objects(ctx: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not ctx:
        return []
    objects = ctx.get("objects") or []
    return objects if isinstance(objects, list) else []


def _mentioned_object(task: str, ctx: Optional[Dict[str, Any]]) -> Optional[str]:
    """Longest scene-object name appearing verbatim in the task (if any)."""
    lowered = task.lower()
    best = None
    for entry in _ctx_objects(ctx):
        name = entry.get("name", "") if isinstance(entry, dict) else ""
        if name and len(name) >= 3 and name.lower() in lowered:
            if best is None or len(name) > len(best):
                best = name
    return best


def _match_objects_by_words(task: str, ctx: Optional[Dict[str, Any]],
                            cap: int = 200) -> List[str]:
    """Objects whose names contain a significant task word (e.g. 'tower')."""
    words = {w.strip(".,!?\"'").lower() for w in task.split()}
    words = {w for w in words if len(w) >= 4}
    if not words or not ctx:
        return []
    hits = []
    for entry in _ctx_objects(ctx):
        name = entry.get("name", "") if isinstance(entry, dict) else ""
        lowered = name.lower()
        if any(w in lowered for w in words):
            hits.append(name)
        if len(hits) >= cap:
            break
    return hits


def _inspect_step() -> Step:
    return _step("scene.inspect", {"object_limit": 150}, "Analyze scene")


def _verify_step(auto_fix: bool = False) -> Step:
    return _step("debug.diagnose", {"auto_fix": auto_fix}, "Verify scene")


# ---------------------------------------------------------------------------
# Domain builders — each returns plan steps for its specialty
# ---------------------------------------------------------------------------

def plan_modeling(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    # Cross-domain: an actual character belongs to the rig builder.
    if _has(task, "character", "human", "humanoid", "person", "mannequin"):
        return plan_character(task, ctx)
    if _has(task, "house", "building", "tower", "skyscraper"):
        return plan_procedural(task, ctx)
    if _has(task, "robot", "mech", "droid", "android"):
        return _build_robot(task)
    if _has(task, "car", "vehicle", "truck", "tank"):
        return _build_car(task)
    if _has(task, "sword", "blade", "weapon", "gun"):
        return _build_sword(task)
    if _has(task, "chair", "table", "furniture", "desk", "bed"):
        return _build_chair(task)
    if _has(task, "creature", "monster", "alien", "dragon"):
        return _build_creature(task)
    return _build_generic(task)


def _build_robot(task: str) -> List[Step]:
    name = _extract_name(task, "Robot")
    steps = [
        _step("material.create", {"name": f"{name}_Metal", "preset": "metal",
                                  "base_color": [0.55, 0.57, 0.6, 1.0],
                                  "roughness": 0.35}, "Create robot metal"),
        _step("material.create", {"name": f"{name}_Glow", "preset": "scifi_glow"},
              "Create glow material"),
        _step("modeling.create_primitive", {"kind": "CUBE", "name": f"{name}_Torso",
                                            "location": [0, 0, 1.4], "size": 1.0,
                                            "scale": [0.7, 0.45, 0.8],
                                            "collection": name,
                                            "material": f"{name}_Metal"}, "Create torso"),
        _step("modeling.create_primitive", {"kind": "CUBE", "name": f"{name}_Head",
                                            "location": [0, 0, 2.35], "size": 0.6,
                                            "collection": name,
                                            "material": f"{name}_Metal"}, "Create head"),
        _step("modeling.create_primitive", {"kind": "SPHERE_UV", "name": f"{name}_Eye_L",
                                            "location": [-0.15, -0.32, 2.4], "size": 0.14,
                                            "collection": name,
                                            "material": f"{name}_Glow"}, "Create eyes"),
        _step("modeling.create_primitive", {"kind": "SPHERE_UV", "name": f"{name}_Eye_R",
                                            "location": [0.15, -0.32, 2.4], "size": 0.14,
                                            "collection": name,
                                            "material": f"{name}_Glow"}, "Create eyes"),
    ]
    for side, sx in (("L", -1), ("R", 1)):
        steps += [
            _step("modeling.create_primitive", {"kind": "CYLINDER",
                                                "name": f"{name}_Arm_{side}",
                                                "location": [sx * 0.95, 0, 1.4],
                                                "size": 0.28, "collection": name,
                                                "material": f"{name}_Metal"},
                  f"Create arm {side}"),
            _step("modeling.create_primitive", {"kind": "CYLINDER",
                                                "name": f"{name}_Leg_{side}",
                                                "location": [sx * 0.32, 0, 0.45],
                                                "size": 0.34, "collection": name,
                                                "material": f"{name}_Metal"},
                  f"Create leg {side}"),
        ]
    steps += [
        _step("modeling.create_primitive", {"kind": "CYLINDER", "name": f"{name}_Antenna",
                                            "location": [0.2, 0, 2.85], "size": 0.1,
                                            "collection": name,
                                            "material": f"{name}_Metal"}, "Create antenna"),
        _step("modeling.bevel", {"name": f"{name}_Torso", "width": 0.04}, "Bevel torso"),
        _step("modeling.bevel", {"name": f"{name}_Head", "width": 0.03}, "Bevel head"),
        _step("modeling.set_shade", {"name": f"{name}_Head", "smooth": True}, "Shade head"),
    ]
    return steps


def _build_car(task: str) -> List[Step]:
    name = _extract_name(task, "Car")
    color = [0.7, 0.08, 0.08, 1.0] if _has(task, "red") else [0.1, 0.15, 0.7, 1.0]
    steps = [
        _step("material.create", {"name": f"{name}_Paint", "preset": "metal",
                                  "base_color": color, "roughness": 0.25}, "Create car paint"),
        _step("material.create", {"name": f"{name}_Glass", "preset": "glass"}, "Create glass"),
        _step("material.create", {"name": f"{name}_Tire", "preset": "principled",
                                  "base_color": [0.05, 0.05, 0.05, 1.0],
                                  "roughness": 0.9}, "Create tires"),
        _step("modeling.create_primitive", {"kind": "CUBE", "name": f"{name}_Body",
                                            "location": [0, 0, 0.7], "size": 1.0,
                                            "scale": [2.2, 1.0, 0.45],
                                            "collection": name,
                                            "material": f"{name}_Paint"}, "Create body"),
        _step("modeling.create_primitive", {"kind": "CUBE", "name": f"{name}_Cabin",
                                            "location": [-0.2, 0, 1.25], "size": 1.0,
                                            "scale": [1.0, 0.85, 0.35],
                                            "collection": name,
                                            "material": f"{name}_Glass"}, "Create cabin"),
    ]
    for i, (wx, wy) in enumerate([(1.4, 1.0), (1.4, -1.0), (-1.4, 1.0), (-1.4, -1.0)]):
        steps.append(_step("modeling.create_primitive", {"kind": "CYLINDER",
                                                         "name": f"{name}_Wheel_{i}",
                                                         "location": [wx, wy, 0.4],
                                                         "rotation_deg": [90, 0, 0],
                                                         "size": 0.8, "collection": name,
                                                         "material": f"{name}_Tire"},
                           f"Create wheel {i}"))
    steps.append(_step("modeling.bevel", {"name": f"{name}_Body", "width": 0.06}, "Bevel body"))
    return steps


def _build_sword(task: str) -> List[Step]:
    name = _extract_name(task, "Sword")
    return [
        _step("material.create", {"name": f"{name}_Steel", "preset": "metal",
                                  "base_color": [0.75, 0.77, 0.8, 1.0],
                                  "roughness": 0.2}, "Create steel"),
        _step("material.create", {"name": f"{name}_Gold", "preset": "metal",
                                  "base_color": [1.0, 0.72, 0.25, 1.0],
                                  "roughness": 0.3}, "Create gold"),
        _step("modeling.create_primitive", {"kind": "CUBE", "name": f"{name}_Blade",
                                            "location": [0, 0, 1.1], "size": 1.0,
                                            "scale": [0.06, 0.02, 1.0],
                                            "collection": name,
                                            "material": f"{name}_Steel"}, "Create blade"),
        _step("modeling.create_primitive", {"kind": "CUBE", "name": f"{name}_Guard",
                                            "location": [0, 0, 0.05], "size": 1.0,
                                            "scale": [0.3, 0.06, 0.05],
                                            "collection": name,
                                            "material": f"{name}_Gold"}, "Create guard"),
        _step("modeling.create_primitive", {"kind": "CYLINDER", "name": f"{name}_Grip",
                                            "location": [0, 0, -0.25], "size": 0.12,
                                            "collection": name,
                                            "material": f"{name}_Gold"}, "Create grip"),
        _step("modeling.create_primitive", {"kind": "SPHERE_UV", "name": f"{name}_Pommel",
                                            "location": [0, 0, -0.5], "size": 0.14,
                                            "collection": name,
                                            "material": f"{name}_Gold"}, "Create pommel"),
        _step("modeling.set_shade", {"name": f"{name}_Pommel", "smooth": True}, "Shade pommel"),
    ]


def _build_chair(task: str) -> List[Step]:
    name = _extract_name(task, "Chair")
    steps = [
        _step("material.create", {"name": f"{name}_Wood", "preset": "wood"}, "Create wood"),
        _step("modeling.create_primitive", {"kind": "CUBE", "name": f"{name}_Seat",
                                            "location": [0, 0, 0.55], "size": 1.0,
                                            "scale": [0.3, 0.3, 0.04],
                                            "collection": name,
                                            "material": f"{name}_Wood"}, "Create seat"),
        _step("modeling.create_primitive", {"kind": "CUBE", "name": f"{name}_Back",
                                            "location": [0, 0.28, 1.0], "size": 1.0,
                                            "scale": [0.3, 0.04, 0.3],
                                            "collection": name,
                                            "material": f"{name}_Wood"}, "Create back"),
    ]
    for i, (lx, ly) in enumerate([(0.25, 0.25), (0.25, -0.25), (-0.25, 0.25), (-0.25, -0.25)]):
        steps.append(_step("modeling.create_primitive", {"kind": "CYLINDER",
                                                         "name": f"{name}_Leg_{i}",
                                                         "location": [lx, ly, 0.26],
                                                         "size": 0.09, "collection": name,
                                                         "material": f"{name}_Wood"},
                           f"Create leg {i}"))
    return steps


def _build_creature(task: str) -> List[Step]:
    name = _extract_name(task, "Creature")
    steps = [
        _step("material.create", {"name": f"{name}_Skin", "preset": "skin",
                                  "base_color": [0.3, 0.55, 0.3, 1.0]}, "Create skin"),
        _step("modeling.create_primitive", {"kind": "SPHERE_ICO", "name": f"{name}_Body",
                                            "location": [0, 0, 1.0], "size": 1.6,
                                            "scale": [1.2, 0.9, 1.0],
                                            "collection": name,
                                            "material": f"{name}_Skin"}, "Create body"),
        _step("modeling.create_primitive", {"kind": "SPHERE_UV", "name": f"{name}_Head",
                                            "location": [0, -0.9, 1.6], "size": 0.8,
                                            "collection": name,
                                            "material": f"{name}_Skin"}, "Create head"),
        _step("modeling.create_primitive", {"kind": "SPHERE_UV", "name": f"{name}_Eye_L",
                                            "location": [-0.2, -1.25, 1.7], "size": 0.16,
                                            "collection": name}, "Create eyes"),
        _step("modeling.create_primitive", {"kind": "SPHERE_UV", "name": f"{name}_Eye_R",
                                            "location": [0.2, -1.25, 1.7], "size": 0.16,
                                            "collection": name}, "Create eyes"),
    ]
    for i in range(4):
        steps.append(_step("modeling.create_primitive", {"kind": "CONE",
                                                         "name": f"{name}_Spike_{i}",
                                                         "location": [0, 0.5 - i * 0.35, 1.9],
                                                         "size": 0.3, "collection": name,
                                                         "material": f"{name}_Skin"},
                           f"Create spike {i}"))
    steps += [
        _step("modeling.subdivide", {"name": f"{name}_Body", "levels": 2}, "Smooth body"),
        _step("modeling.set_shade", {"name": f"{name}_Body", "smooth": True}, "Shade body"),
    ]
    return steps


def _build_generic(task: str) -> List[Step]:
    name = _extract_name(task, "Subject")
    return [
        _step("modeling.create_primitive", {"kind": "CUBE", "name": f"{name}_Base",
                                            "location": [0, 0, 0.5], "size": 1.4,
                                            "collection": name}, "Create base form"),
        _step("modeling.create_primitive", {"kind": "SPHERE_UV", "name": f"{name}_Detail",
                                            "location": [0, 0, 1.6], "size": 0.9,
                                            "collection": name}, "Create detail form"),
        _step("modeling.create_primitive", {"kind": "TORUS", "name": f"{name}_Accent",
                                            "location": [0, 0, 0.5], "size": 1.8,
                                            "collection": name}, "Create accent"),
        _step("modeling.bevel", {"name": f"{name}_Base", "width": 0.05}, "Bevel base"),
        _step("modeling.set_shade", {"name": f"{name}_Detail", "smooth": True}, "Shade detail"),
        _step("material.create", {"name": f"{name}_Mat", "preset": "principled"}, "Create material"),
        _step("material.assign", {"material": f"{name}_Mat", "pattern": f"{name}_*"},
              "Assign material"),
    ]


def plan_material(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    lowered = task.lower()
    preset = "principled"
    extra: Dict[str, Any] = {}
    if "brushed" in lowered:
        preset = "brushed_metal"
    elif "glass" in lowered:
        preset = "glass"
    elif "wood" in lowered:
        preset = "wood"
    elif _has(task, "stone", "marble", "concrete"):
        preset = "stone"
    elif "skin" in lowered:
        preset = "skin"
    elif "ceramic" in lowered:
        preset = "ceramic"
    elif "fabric" in lowered or "cloth" in lowered:
        preset = "fabric"
    elif "plastic" in lowered:
        preset = "plastic"
    elif _has(task, "gold"):
        preset, extra = "metal", {"base_color": [1.0, 0.72, 0.25, 1.0], "roughness": 0.3}
    elif _has(task, "copper"):
        preset, extra = "metal", {"base_color": [0.72, 0.35, 0.2, 1.0], "roughness": 0.35}
    elif _has(task, "chrome"):
        preset, extra = "metal", {"base_color": [0.9, 0.9, 0.92, 1.0], "roughness": 0.08}
    elif _has(task, "metal", "steel", "iron", "aluminium", "aluminum"):
        preset = "metal"
        if _has(task, "rust"):
            extra = {"base_color": [0.5, 0.25, 0.12, 1.0], "roughness": 0.75}
    elif _has(task, "neon", "scifi", "sci-fi", "cyber", "laser"):
        preset = "scifi_glow"
    elif _has(task, "emissive", "glow", "emit"):
        preset = "emissive"
    elif "stylized" in lowered or "toon" in lowered:
        preset = "stylized"
    name = _extract_name(task, f"AI_{preset.title().replace('_', '')}")
    create_params: Dict[str, Any] = {"name": name, "preset": preset}
    create_params.update(extra)
    assign: Dict[str, Any] = {"material": name}
    mentioned = _mentioned_object(task, ctx)
    if mentioned:
        assign["objects"] = [mentioned]
    elif "selected" in lowered:
        assign["use_selection"] = True
    # else: assign falls back to the active object inside the tool.
    return [_step("material.create", create_params, f"Create {preset} material"),
            _step("material.assign", assign, "Assign material")]


def plan_character(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    name = _extract_name(task, "Hero")
    height = 1.8
    match = re.search(r"(\d+(?:\.\d+)?)\s*m(?:eters?)?\b", task.lower())
    if match:
        try:
            height = max(0.5, min(float(match.group(1)), 5.0))
        except ValueError:
            pass
    steps = [_step("character.build_simple_humanoid",
                   {"name": name, "height": height}, f"Build {name}")]
    if _has(task, "pose", "wave", "raise", "arms up", "t-pose", "tpose"):
        steps.append(_step("character.create_pose",
                           {"armature": f"{name}_Rig",
                            "pose": {f"UpperArm_L": {"rotation_deg": [0, 0, 140]},
                                     f"Forearm_L": {"rotation_deg": [0, 0, 20]}}},
                           "Create wave pose"))
    if _has(task, "ik", "inverse kinematic"):
        steps.append(_step("character.add_ik",
                           {"armature": f"{name}_Rig", "bone": "Shin_L",
                            "chain_count": 2}, "Add leg IK"))
    return steps


def plan_animation(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    target = _mentioned_object(task, ctx) or "$active_object"
    seconds = _extract_seconds(task, 4)
    fps = 30 if "30" in task else 24
    frames = fps * seconds
    steps = [_step("animation.set_timeline",
                   {"start": 1, "end": frames, "current": 1, "fps": fps},
                   f"Set timeline ({seconds}s @ {fps}fps)")]
    if _has(task, "camera") and (not ctx or (ctx.get("cameras")) or True):
        # Camera orbit around the subject.
        subject = _mentioned_object(task, ctx) or "$active_object"
        steps.append(_step("cutscene.create_shot",
                           {"name": "Anim_Orbit", "start": 1, "end": frames,
                            "location": [8, -8, 4], "look_at_object": subject,
                            "movement": "ORBIT", "intensity": 120},
                           "Animate camera orbit"))
        return steps
    if _has(task, "walk", "run"):
        steps.append(_step("animation.animate_transform",
                           {"object": target,
                            "keys": [{"frame": 1, "location": [0, -4, 0]},
                                     {"frame": frames // 2, "location": [0, 0, 0.15]},
                                     {"frame": frames, "location": [0, 4, 0]}],
                            "interpolation": "LINEAR"},
                           "Animate walk-through"))
    elif _has(task, "turntable", "rotate", "spin", "360"):
        steps.append(_step("animation.animate_transform",
                           {"object": target,
                            "keys": [{"frame": 1, "rotation_deg": [0, 0, 0]},
                                     {"frame": frames, "rotation_deg": [0, 0, 360]}],
                            "interpolation": "LINEAR"},
                           "Animate turntable"))
    elif _has(task, "jump", "bounce", "hop"):
        steps.append(_step("animation.animate_transform",
                           {"object": target,
                            "keys": [{"frame": 1, "location": [0, 0, 0]},
                                     {"frame": frames // 2, "location": [0, 0, 2]},
                                     {"frame": frames, "location": [0, 0, 0]}],
                            "interpolation": "BEZIER"},
                           "Animate jump"))
    else:  # Gentle float loop default.
        steps.append(_step("animation.animate_transform",
                           {"object": target,
                            "keys": [{"frame": 1, "location": [0, 0, 0]},
                                     {"frame": frames // 2, "location": [0, 0, 0.5]},
                                     {"frame": frames, "location": [0, 0, 0]}],
                            "interpolation": "SINE"},
                           "Animate float loop"))
    if _has(task, "loop", "walk", "run", "turntable", "spin", "rotate", "float"):
        steps.append(_step("animation.create_loop", {"object": target}, "Make looping"))
    return steps


def plan_environment(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    lowered = task.lower()
    preset = "city"
    for candidate in ("forest", "desert", "interior", "ruins", "village",
                      "lab", "battlefield", "city"):
        if candidate in lowered:
            preset = candidate
            break
    if _has(task, "castle", "fortress", "medieval"):
        preset = "city"
    if _has(task, "jungle", "woods"):
        preset = "forest"
    if _has(task, "dune", "dunes"):
        preset = "desert"
    if _has(task, "laboratory", "sci-fi", "scifi", "space station", "spaceship"):
        preset = "lab"
    if _has(task, "temple"):
        preset = "ruins"
    if _has(task, "battle", "war", "warzone"):
        preset = "battlefield"
    if _has(task, "room") and preset == "city":
        preset = "interior"
    size = 60.0 if _has(task, "large", "huge", "vast") else (
        20.0 if _has(task, "small", "tiny") else 40.0)
    match = re.search(r"(\d+)\s*m\b", lowered)
    if match:
        try:
            size = max(10.0, min(float(match.group(1)), 500.0))
        except ValueError:
            pass
    steps = [_step("environment.create_preset",
                   {"preset": preset, "size": size, "seed": 7,
                    "with_lighting": True}, f"Build {preset} environment"),
             _step("camera.create",
                   {"name": f"{preset.title()}_Wide",
                    "location": [size * 0.45, -size * 0.45, size * 0.3],
                    "look_at": [0, 0, 2]}, "Frame wide camera")]
    if _has(task, "fog", "mist", "atmosphere", "moody", "volumetric"):
        steps.append(_step("environment.set_atmosphere", {"density": 0.03},
                           "Add atmosphere"))
    return steps


def plan_procedural(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    if _has(task, "stairs", "staircase"):
        return [_step("procedural.create_stairs",
                      {"steps": _extract_int(task, 12, 1, 200)}, "Create stairs")]
    if _has(task, "building", "house", "tower", "skyscraper"):
        floors = _extract_int(task, 0, 1, 60) if re.search(
            r"(\d+)\s*(?:floor|stor)", task.lower()) else 8
        if _has(task, "tall", "skyscraper"):
            floors = max(floors, 20)
        return [_step("procedural.create_building",
                      {"floors": floors,
                       "name": _extract_name(task, "AI_Building")},
                      "Create procedural building")]
    if _has(task, "terrain", "landscape", "displace"):
        return [
            _step("modeling.create_primitive",
                  {"kind": "GRID", "name": "Procedural_Terrain", "size": 40.0,
                   "collection": "Environment"}, "Create terrain grid"),
            _step("nodes.create_geonodes",
                  {"object": "Procedural_Terrain", "name": "AI_Terrain_Displace",
                   "preset": "displace_noise", "noise_scale": 1.5,
                   "strength": 2.0}, "Add noise displacement"),
        ]
    if _has(task, "scatter", "rock") and not _has(task, "forest", "tree"):
        base = _mentioned_object(task, ctx) or "$first_mesh"
        return [_step("environment.scatter_objects",
                      {"base_object": base,
                       "count": _extract_int(task, 60, 1, 2000),
                       "area_size": 30.0, "seed": 3}, "Scatter objects")]
    # Default: procedural forest with Geometry Nodes scattering.
    count = _extract_int(task, 150, 1, 5000)
    return [
        _step("modeling.create_primitive",
              {"kind": "CYLINDER", "name": "Tree_Trunk", "size": 0.5,
               "location": [0, 0, 1.0], "scale": [1, 1, 4.0],
               "collection": "Procedural"}, "Create trunk prototype"),
        _step("modeling.create_primitive",
              {"kind": "CONE", "name": "Tree_Top", "size": 2.4,
               "location": [0, 0, 3.4], "collection": "Procedural"},
              "Create foliage prototype"),
        _step("modeling.join", {"names": ["Tree_Trunk", "Tree_Top"]},
              "Join tree prototype", critical=True),
        _step("modeling.create_primitive",
              {"kind": "GRID", "name": "Forest_Ground", "size": 60.0,
               "collection": "Procedural"}, "Create forest ground"),
        _step("nodes.create_geonodes",
              {"object": "Forest_Ground", "name": "AI_Forest_Scatter",
               "preset": "scatter", "scatter_object": "Tree_Trunk",
               "count": count}, f"Scatter {count} trees", critical=True),
        _step("lighting.setup_preset", {"preset": "three_point"}, "Light forest"),
    ]


def plan_lighting(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    lowered = task.lower()
    preset = "three_point"
    for candidate in ("rim", "dramatic", "horror", "scifi", "studio", "product"):
        if candidate in lowered or (candidate == "scifi" and "sci-fi" in lowered):
            preset = candidate
            break
    if "three-point" in lowered or "three point" in lowered:
        preset = "three_point"
    params: Dict[str, Any] = {"preset": preset, "energy": 400.0}
    mentioned = _mentioned_object(task, ctx)
    if mentioned:
        params["target"] = mentioned
    steps = [_step("lighting.setup_preset", params, f"Build {preset} lighting")]
    if preset in ("scifi", "horror"):
        steps.append(_step("lighting.set_world",
                           {"background_color": [0.01, 0.015, 0.03, 1.0],
                            "strength": 0.4}, "Darken world"))
    elif preset in ("studio", "product"):
        steps.append(_step("lighting.set_world",
                           {"background_color": [0.9, 0.9, 0.92, 1.0],
                            "strength": 1.0}, "Brighten world"))
    if _has(task, "fog", "mist", "atmosphere", "moody", "volumetric"):
        steps.append(_step("environment.set_atmosphere", {"density": 0.025},
                           "Add atmosphere"))
    return steps


def plan_cutscene(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    seconds = _extract_seconds(task, 10)
    fps = 24
    total = fps * seconds
    subject = _mentioned_object(task, ctx) or "$active_object"
    third = total // 3
    shots = [
        {"name": "Shot_01_Wide", "start": 1, "end": third,
         "location": [10, -10, 5], "look_at_object": subject,
         "movement": "PUSH_IN", "intensity": 0.3},
        {"name": "Shot_02_Orbit", "start": third + 1, "end": 2 * third,
         "location": [8, -8, 3], "look_at_object": subject,
         "movement": "ORBIT", "intensity": 100},
        {"name": "Shot_03_Close", "start": 2 * third + 1, "end": total,
         "location": [3.5, -3.5, 2.0], "look_at_object": subject,
         "movement": "PAN", "intensity": 2.0},
    ]
    steps: List[Step] = []
    if ctx is not None and not ctx.get("lights"):
        steps.append(_step("lighting.setup_preset", {"preset": "dramatic",
                                                     "target_point": [0, 0, 1]},
                           "Add cinematic lighting"))
    if _has(task, "walk", "move through", "moves through", "enters", "approaches"):
        steps.append(_step("animation.animate_transform",
                           {"object": subject,
                            "keys": [{"frame": 1, "location": [-8, 0, 0]},
                                     {"frame": total, "location": [2, 0, 0]}],
                            "interpolation": "LINEAR"},
                           "Animate subject path"))
    steps.append(_step("cutscene.build_sequence",
                       {"shots": shots, "fps": fps}, f"Build {seconds}s sequence"))
    if _has(task, "shake", "handheld", "action"):
        steps.append(_step("cutscene.add_camera_shake",
                           {"camera": "Shot_01_Wide", "amplitude": 0.12},
                           "Add camera shake"))
    return steps


def plan_optimization(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    steps = [_step("optimization.analyze", {}, "Analyze performance"),
             _step("optimization.limit_subsurf", {"max_levels": 2}, "Cap subsurf"),
             _step("optimization.remove_doubles", {}, "Weld doubles"),
             _step("optimization.purge_unused", {}, "Purge orphans")]
    if _has(task, "aggressive", "heavy", "decimat", "low-poly", "lowpoly", "mobile"):
        steps.append(_step("optimization.decimate_scene",
                           {"ratio": 0.5, "min_verts": 10000},
                           "Decimate heavy meshes"))
    return steps


def plan_debug(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    return [_step("debug.diagnose", {"auto_fix": True}, "Diagnose and repair")]


def plan_physics(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    targets = _match_objects_by_words(task, ctx)
    mentioned = _mentioned_object(task, ctx)
    if mentioned and mentioned not in targets:
        targets.insert(0, mentioned)
    params: Dict[str, Any] = {"body_type": "ACTIVE", "mass": 1.0,
                              "collision_shape": "CONVEX_HULL"}
    if targets:
        params["objects"] = targets[:200]
    elif "selected" in task.lower():
        params["use_selection"] = True
    else:
        params["objects"] = ["$active_object"]
    steps = [_step("physics.add_rigid_body", params, "Add rigid bodies")]
    gravity = [0, 0, -1.62] if _has(task, "moon", "low gravity") else [0, 0, -9.81]
    steps.append(_step("physics.set_gravity", {"gravity": gravity}, "Set gravity"))
    if _has(task, "cloth"):
        target = mentioned or "$active_object"
        steps.append(_step("physics.add_cloth", {"object": target}, "Add cloth"))
    if _has(task, "wind", "force"):
        steps.append(_step("physics.add_force", {"kind": "WIND", "strength": 15.0},
                           "Add wind"))
    if _has(task, "bake"):
        steps.append(_step("physics.bake_to_keyframes", {}, "Bake simulation"))
    return steps


def plan_render(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    steps = []
    engine = None
    if "cycles" in task.lower():
        engine = "CYCLES"
    elif "eevee" in task.lower():
        engine = "BLENDER_EEVEE"
    config: Dict[str, Any] = {}
    if engine:
        config["engine"] = engine
    if _has(task, "4k", "2160"):
        config["resolution"] = [3840, 2160]
    elif _has(task, "1080", "hd", "full hd"):
        config["resolution"] = [1920, 1080]
    samples = re.search(r"(\d+)\s*samples?", task.lower())
    if samples:
        try:
            config["samples"] = max(1, min(int(samples.group(1)), 100000))
        except ValueError:
            pass
    if config:
        steps.append(_step("rendering.configure", config, "Configure renderer"))
    if _has(task, "render", "still", "image", "picture", "thumbnail", "preview"):
        steps.append(_step("rendering.render", {"frame": "current"},
                           "Render still image"))
    return steps or [_step("rendering.info", {}, "Show render settings")]


def plan_director(task: str, ctx: Optional[Dict[str, Any]]) -> List[Step]:
    steps: List[Step] = []
    # Subject: character > robot/vehicle/prop > none (environment carries it).
    if _has(task, "character", "human", "humanoid", "person", "robot", "mech",
            "car", "vehicle", "creature"):
        steps += plan_modeling(task, ctx)
        subject_note = "subject"
    else:
        subject_note = ""
    # Environment: explicit preset or art-directed default.
    if _has(task, "city", "forest", "desert", "interior", "ruins", "village",
            "lab", "battlefield", "castle", "environment", "world"):
        steps += plan_environment(task, ctx)
    else:
        default_env = "lab" if _has(task, "robot", "scifi", "sci-fi", "cyber",
                                    "space", "futuristic") else "city"
        steps += plan_environment(f"create {default_env} environment", ctx)
    # Mood.
    if _has(task, "dramatic", "moody", "noir", "horror"):
        steps.append(_step("lighting.setup_preset", {"preset": "dramatic"},
                           "Add dramatic lighting"))
    elif _has(task, "scifi", "sci-fi", "neon", "cyber"):
        steps.append(_step("lighting.setup_preset", {"preset": "scifi"},
                           "Add sci-fi lighting"))
    # Motion.
    if _has(task, "walk", "animat", "move", "fly", "drive", "run", "dance"):
        steps += [s for s in plan_animation(task, ctx)
                  if s["tool"] != "animation.set_timeline"]
    # Story.
    seconds = _extract_seconds(task, 8)
    steps += plan_cutscene(f"create a {seconds}-second cinematic of {subject_note}",
                           ctx)
    return steps


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

DOMAIN_BUILDERS = {
    "MODELING": plan_modeling,
    "MATERIAL": plan_material,
    "CHARACTER": plan_character,
    "ANIMATION": plan_animation,
    "ENVIRONMENT": plan_environment,
    "PROCEDURAL": plan_procedural,
    "LIGHTING": plan_lighting,
    "CUTSCENE": plan_cutscene,
    "OPTIMIZATION": plan_optimization,
    "DEBUG": plan_debug,
}

PHYSICS_WORDS = ("rigid", "physics", "gravity", "cloth", "collision", "fall",
                 "collapse", "destruction", "simulate", "bake simulation",
                 "wind", "force field")
RENDER_WORDS = ("render", "cycles", "eevee", "sample", "thumbnail")


def _wants_physics(task: str) -> bool:
    return _has(task, *PHYSICS_WORDS)


def _wants_render(task: str) -> bool:
    return _has(task, *RENDER_WORDS)


def build_plan(task: str, mode: str = "SMART",
               context: Optional[Dict[str, Any]] = None,
               max_steps: int = 60) -> Dict[str, Any]:
    """Build an ordered, dependency-safe tool plan for a task."""
    from ..modes import detect_modes

    task = (task or "").strip()
    mode = (mode or "SMART").upper()
    if not task:
        raise ValueError("build_plan requires a non-empty task.")
    max_steps = max(1, min(int(max_steps or 60), 500))

    notes: List[str] = []
    if mode == "SMART":
        domains = detect_modes(task)
        if _wants_physics(task):
            domains.append("PHYSICS")
        if _wants_render(task):
            domains.append("RENDER")
        # De-dupe cross-routed domains (modeling delegates internally).
        if "MODELING" in domains and "CHARACTER" in domains and _has(
                task, "character", "human", "humanoid", "person"):
            domains.remove("MODELING")
        if "MODELING" in domains and "PROCEDURAL" in domains and _has(
                task, "house", "building", "tower", "skyscraper"):
            domains.remove("MODELING")
        # Order pipeline: builders already respect internal order; sort known modes.
        order = {"MODELING": 10, "MATERIAL": 20, "CHARACTER": 30,
                 "ENVIRONMENT": 40, "PROCEDURAL": 45, "PHYSICS": 50,
                 "ANIMATION": 60, "LIGHTING": 70, "CUTSCENE": 80,
                 "RENDER": 85, "OPTIMIZATION": 90, "DEBUG": 95}
        domains = sorted(set(domains), key=lambda d: order.get(d, 99))
        if not domains:
            notes.append("No specialist domain detected — inspect the scene, "
                         "then describe a concrete modeling/material/animation task.")
            steps = [_inspect_step()]
            _number(steps)
            return {"task": task, "mode": mode, "detected_domains": [],
                    "steps": steps, "notes": notes}
    elif mode == "DIRECTOR":
        domains = ["DIRECTOR"]
    elif mode in DOMAIN_BUILDERS:
        domains = [mode]
    else:
        domains = ["MODELING"]
        notes.append(f"Unknown mode '{mode}' — fell back to MODELING.")

    steps: List[Step] = [_inspect_step()]
    for domain in domains:
        if domain == "DIRECTOR":
            steps += plan_director(task, context)
        elif domain == "PHYSICS":
            steps += plan_physics(task, context)
        elif domain == "RENDER":
            steps += plan_render(task, context)
        else:
            steps += DOMAIN_BUILDERS[domain](task, context)
    # Verify complex runs (unless the run IS a debug/optimization pass).
    if len(steps) >= 6 and not (set(domains) & {"DEBUG", "OPTIMIZATION"}):
        steps.append(_verify_step())
    if len(steps) > max_steps:
        steps = steps[:max_steps - 1] + [_verify_step()]
        notes.append(f"Plan truncated to {max_steps} steps.")
    _number(steps)
    detected = [d for d in domains if d != "DIRECTOR"] or domains
    return {"task": task, "mode": mode, "detected_domains": detected,
            "steps": steps, "notes": notes}


def _number(steps: List[Step]) -> None:
    for i, step in enumerate(steps, 1):
        step["seq"] = i
        step["total"] = len(steps)
