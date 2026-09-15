"""Cutscene tools: cinematic shots, sequences, camera shake."""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

MOVEMENTS = ("STATIC", "PUSH_IN", "PULL_OUT", "ORBIT", "PAN", "TRUCK")


def _look_at(cam_loc, target):
    from mathutils import Vector
    direction = Vector(target) - Vector(cam_loc)
    if direction.length < 1e-6:
        return (math.radians(60), 0, 0)
    return tuple(direction.to_track_quat("-Z", "Y").to_euler())


def _build_movement_keys(movement: str, base, target, start: int, end: int,
                         intensity: float) -> List[Dict[str, Any]]:
    import math as _math
    bx, by, bz = base
    tx, ty, tz = target
    keys: List[Dict[str, Any]] = []
    if movement == "STATIC":
        return keys
    if movement in ("PUSH_IN", "PULL_OUT"):
        k = BU.clamp(intensity, 0.05, 0.9)
        near = (bx + (tx - bx) * k, by + (ty - by) * k,
                max(0.3, bz + (tz - bz) * k))
        order = [(start, base), (end, near)] if movement == "PUSH_IN" else [(start, near), (end, base)]
        for frame, loc in order:
            keys.append({"frame": frame, "location": list(loc),
                         "rotation_deg": [math.degrees(a) for a in _look_at(loc, target)]})
    elif movement == "ORBIT":
        import mathutils
        radius = max(0.5, _math.hypot(bx - tx, by - ty))
        arc = _math.radians(BU.clamp(intensity, 5, 360) if intensity > 3 else 90)
        base_angle = _math.atan2(by - ty, bx - tx)
        steps = 5
        for i in range(steps):
            angle = base_angle + arc * i / (steps - 1)
            loc = (tx + radius * _math.cos(angle), ty + radius * _math.sin(angle), bz)
            frame = int(start + (end - start) * i / (steps - 1)) if steps > 1 else start
            keys.append({"frame": frame, "location": list(loc),
                         "rotation_deg": [math.degrees(a) for a in _look_at(loc, target)]})
    else:  # PAN / TRUCK: lateral move perpendicular to view direction.
        dx, dy = tx - bx, ty - by
        length = _math.hypot(dx, dy) or 1.0
        px, py = -dy / length, dx / length
        dist = BU.clamp(intensity, 0.5, 50.0)
        a = (bx - px * dist / 2, by - py * dist / 2, bz)
        b = (bx + px * dist / 2, by + py * dist / 2, bz)
        keys = [{"frame": start, "location": list(a),
                 "rotation_deg": [math.degrees(v) for v in _look_at(a, target)]},
                {"frame": end, "location": list(b),
                 "rotation_deg": [math.degrees(v) for v in _look_at(b, target)]}]
    return keys


@register_tool("cutscene.create_shot", "cutscene", "Create cinematic shot",
               "Camera + movement animation + timeline marker binding.",
               params={
                   "name": {"type": "string", "default": "Shot"},
                   "start": {"type": "int", "required": True},
                   "end": {"type": "int", "required": True},
                   "location": {"type": "list", "default": [7, -7, 4]},
                   "look_at": {"type": "list", "default": None},
                   "look_at_object": {"type": "string", "default": ""},
                   "lens": {"type": "float", "default": 50.0},
                   "movement": {"type": "string", "default": "PUSH_IN",
                                "choices": list(MOVEMENTS)},
                   "intensity": {"type": "float", "default": 0.35,
                                 "description": "PUSH/PULL fraction, ORBIT degrees, PAN/TRUCK units"},
                   "interpolation": {"type": "string", "default": "LINEAR"},
               })
def create_shot(params: Dict[str, Any]) -> Dict[str, Any]:
    from .animation_tools import animate_transform
    from .camera_tools import camera_create

    require_bpy()
    start, end = int(params["start"]), int(params["end"])
    if end <= start:
        raise ToolError("INVALID_PARAMS", "Shot end must be after start.")
    if params.get("look_at_object"):
        tgt = BU.require_object(params["look_at_object"])
        target = tuple(tgt.matrix_world.translation)
    else:
        target = BU.to_vec3(params.get("look_at"), (0, 0, 1))
    base = BU.to_vec3(params.get("location"), (7, -7, 4))
    cam = camera_create({"name": str(params.get("name", "Shot")),
                         "location": list(base),
                         "look_at": list(target),
                         "lens": params.get("lens", 50.0),
                         "set_active": False,
                         "collection": "Cameras"})["name"]
    movement = params.get("movement", "PUSH_IN")
    keys = _build_movement_keys(movement, base, target, start, end,
                                float(params.get("intensity", 0.35)))
    keyed = []
    if keys:
        keyed = animate_transform({"object": cam, "keys": keys,
                                   "interpolation": params.get("interpolation", "LINEAR")})["frames"]
    scene = BU.ctx_scene()
    marker = scene.timeline_markers.new(name=str(params.get("name", "Shot")), frame=start)
    import bpy
    marker.camera_data = bpy.data.objects[cam]
    return {"shot": params.get("name", "Shot"), "camera": cam,
            "marker": marker.name, "frames": [start, end],
            "movement": movement, "keyed_frames": keyed}


@register_tool("cutscene.build_sequence", "cutscene", "Build cutscene sequence",
               "Build a full multi-shot cinematic (cameras + markers + timeline).",
               params={
                   "shots": {"type": "list", "required": True,
                             "description": "[{name, start, end, location?, look_at_object?, look_at?, lens?, movement?, intensity?}]"},
                   "fps": {"type": "int", "default": None},
                   "set_frame_range": {"type": "bool", "default": True},
               })
def build_sequence(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    shots = params.get("shots") or []
    if not shots:
        raise ToolError("INVALID_PARAMS", "shots must be a non-empty list.")
    made = []
    for i, shot in enumerate(shots):
        if not isinstance(shot, dict) or "start" not in shot or "end" not in shot:
            raise ToolError("INVALID_PARAMS", "Each shot needs {name?, start, end, ...}.")
        spec = dict(shot)
        spec.setdefault("name", f"Shot_{i + 1:02d}")
        made.append(create_shot(spec))
    scene = BU.ctx_scene()
    if params.get("set_frame_range", True):
        scene.frame_start = min(s["frames"][0] for s in made)
        scene.frame_end = max(s["frames"][1] for s in made)
    if params.get("fps"):
        scene.render.fps = max(1, min(int(params["fps"]), 240))
    import bpy
    scene.camera = bpy.data.objects[made[0]["camera"]]
    total = scene.frame_end - scene.frame_start + 1
    return {"shots": made, "frame_range": [scene.frame_start, scene.frame_end],
            "seconds": round(total / scene.render.fps, 2)}


@register_tool("cutscene.add_camera_shake", "cutscene", "Camera shake",
               "Add procedural noise shake to a camera's motion.",
               params={
                   "camera": {"type": "string", "required": True},
                   "start": {"type": "int", "default": None},
                   "end": {"type": "int", "default": None},
                   "amplitude": {"type": "float", "default": 0.15},
                   "frequency": {"type": "float", "default": 2.0},
                   "include_rotation": {"type": "bool", "default": False},
               })
def camera_shake(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    cam = BU.require_object(params["camera"])
    if cam.type != "CAMERA":
        raise ToolError("TOOL_FAILED", f"'{cam.name}' is not a camera.")
    scene = BU.ctx_scene()
    start = int(params.get("start", scene.frame_start))
    end = int(params.get("end", scene.frame_end))
    if cam.animation_data is None:
        cam.animation_data_create()
    if cam.animation_data.action is None:
        cam.animation_data.action = bpy.data.actions.new(f"{cam.name}_Shake")
    action = cam.animation_data.action
    paths = ["location"] + (["rotation_euler"] if params.get("include_rotation") else [])
    modified = []
    for path in paths:
        for index in range(3):
            curve = action.fcurves.find(path, index=index)
            if curve is None:
                try:
                    curve = action.fcurves.new(path, index=index)
                except RuntimeError:
                    continue
                base_value = getattr(cam, path)[index]
                for frame in (start, end):
                    try:
                        point = curve.keyframe_points.insert(frame, base_value)
                        point.interpolation = "LINEAR"
                    except (AttributeError, RuntimeError, TypeError):
                        pass
            if any(m.type == "NOISE" for m in curve.modifiers):
                continue
            try:
                mod = curve.modifiers.new(type="NOISE")
                mod.strength = float(params.get("amplitude", 0.15))
                mod.scale = max(0.01, float(params.get("frequency", 2.0)) * 10.0)
                modified.append(f"{path}[{index}]")
            except (AttributeError, RuntimeError, TypeError):
                continue
    return {"camera": cam.name, "shake_curves": modified}


@register_tool("cutscene.list_shots", "cutscene", "List shots",
               "List timeline markers bound to cameras.",
               params={})
def list_shots(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    scene = BU.ctx_scene()
    shots = []
    for marker in scene.timeline_markers:
        try:
            cam = marker.camera_data
        except (AttributeError, RuntimeError):
            cam = None
        if cam is not None:
            shots.append({"marker": marker.name, "frame": marker.frame,
                          "camera": cam.name})
    shots.sort(key=lambda s: s["frame"])
    return {"shots": shots}
