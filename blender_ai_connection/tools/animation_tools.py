"""Animation tools: timeline, keyframes, interpolation, loops."""

from __future__ import annotations

from typing import Any, Dict, List

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

INTERPOLATIONS = ("CONSTANT", "LINEAR", "BEZIER", "SINE", "QUAD", "CUBIC",
                  "QUART", "QUINT", "EXPO", "CIRC", "BACK", "BOUNCE", "ELASTIC")


def _fcurves_of(obj, data_paths=None):
    adt = getattr(obj, "animation_data", None)
    action = getattr(adt, "action", None) if adt else None
    if action is None:
        return []
    curves = list(getattr(action, "fcurves", []) or [])
    if data_paths:
        wanted = set(data_paths)
        curves = [c for c in curves if c.data_path in wanted]
    return curves


@register_tool("animation.set_timeline", "animation", "Set timeline",
               "Configure frame range, current frame and fps.",
               params={
                   "start": {"type": "int", "default": None},
                   "end": {"type": "int", "default": None},
                   "current": {"type": "int", "default": None},
                   "fps": {"type": "int", "default": None},
               })
def set_timeline(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    scene = BU.ctx_scene()
    if params.get("start") is not None:
        scene.frame_start = int(params["start"])
    if params.get("end") is not None:
        scene.frame_end = int(params["end"])
    if scene.frame_end < scene.frame_start:
        scene.frame_end = scene.frame_start + 1
    if params.get("current") is not None:
        scene.frame_set(int(params["current"]))
    if params.get("fps") is not None:
        scene.render.fps = max(1, min(int(params["fps"]), 240))
    return {"start": scene.frame_start, "end": scene.frame_end,
            "current": scene.frame_current, "fps": scene.render.fps}


@register_tool("animation.set_keyframe", "animation", "Insert keyframe",
               "Set a property value (optional) and keyframe it at a frame.",
               params={
                   "object": {"type": "string", "required": True},
                   "data_path": {"type": "string", "required": True,
                                 "description": "e.g. location, rotation_euler, scale"},
                   "frame": {"type": "int", "required": True},
                   "value": {"type": "list", "default": None},
               })
def set_keyframe(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    path = params["data_path"]
    if params.get("value") is not None and path in ("location", "rotation_euler", "scale"):
        vals = BU.to_vec3(params["value"])
        if path == "rotation_euler":
            import math
            vals = tuple(math.radians(v) for v in vals)
        setattr(obj, path, vals)
    try:
        obj.keyframe_insert(data_path=path, frame=int(params["frame"]))
    except (AttributeError, RuntimeError, TypeError) as exc:
        raise ToolError("TOOL_FAILED", f"Keyframe failed on '{path}': {exc}")
    return {"object": obj.name, "data_path": path, "frame": int(params["frame"])}


@register_tool("animation.animate_transform", "animation", "Animate transform",
               "Keyframe a full transform sequence: [{frame, location, rotation_deg, scale}].",
               params={
                   "object": {"type": "string", "required": True},
                   "keys": {"type": "list", "required": True},
                   "interpolation": {"type": "string", "default": "BEZIER",
                                     "choices": list(INTERPOLATIONS)},
               })
def animate_transform(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    keys = params.get("keys") or []
    if not keys:
        raise ToolError("INVALID_PARAMS", "keys must be a non-empty list.")
    frames: List[int] = []
    for key in keys:
        if not isinstance(key, dict) or "frame" not in key:
            raise ToolError("INVALID_PARAMS", "Each key needs {frame, ...}.")
        frame = int(key["frame"])
        if key.get("location") is not None:
            obj.location = BU.to_vec3(key["location"])
        if key.get("rotation_deg") is not None:
            obj.rotation_euler = BU.deg_to_rad(key["rotation_deg"])
        if key.get("scale") is not None:
            obj.scale = BU.to_vec3(key["scale"], (1, 1, 1))
        try:
            obj.keyframe_insert(data_path="location", frame=frame)
            obj.keyframe_insert(data_path="rotation_euler", frame=frame)
            obj.keyframe_insert(data_path="scale", frame=frame)
        except (AttributeError, RuntimeError, TypeError) as exc:
            raise ToolError("TOOL_FAILED", f"Keyframe at {frame} failed: {exc}")
        frames.append(frame)
    interp = params.get("interpolation", "BEZIER")
    touched = 0
    for curve in _fcurves_of(obj, ("location", "rotation_euler", "scale")):
        for point in curve.keyframe_points:
            if int(point.co.x) in frames:
                try:
                    point.interpolation = interp
                    touched += 1
                except (AttributeError, TypeError):
                    pass
    return {"object": obj.name, "frames": sorted(frames),
            "interpolation": interp, "keys_touched": touched}


@register_tool("animation.set_interpolation", "animation", "Set interpolation",
               "Change interpolation of an object's F-curves.",
               params={
                   "object": {"type": "string", "required": True},
                   "interpolation": {"type": "string", "default": "BEZIER",
                                     "choices": list(INTERPOLATIONS)},
                   "data_paths": {"type": "list", "default": []},
               })
def set_interpolation(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    curves = _fcurves_of(obj, params.get("data_paths") or None)
    if not curves:
        raise ToolError("TOOL_FAILED", f"'{obj.name}' has no animation curves.")
    touched = 0
    for curve in curves:
        for point in curve.keyframe_points:
            try:
                point.interpolation = params.get("interpolation", "BEZIER")
                touched += 1
            except (AttributeError, TypeError):
                pass
    return {"object": obj.name, "keys_touched": touched}


@register_tool("animation.create_loop", "animation", "Make looping",
               "Add CYCLES modifiers so the animation loops seamlessly.",
               params={
                   "object": {"type": "string", "required": True},
                   "data_paths": {"type": "list", "default": []},
                   "mode": {"type": "string", "default": "REPEAT",
                            "choices": ["REPEAT", "MIRROR"]},
               })
def create_loop(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    curves = _fcurves_of(obj, params.get("data_paths") or None)
    if not curves:
        raise ToolError("TOOL_FAILED", f"'{obj.name}' has no animation curves.")
    added = 0
    for curve in curves:
        if any(m.type == "CYCLES" for m in curve.modifiers):
            continue
        try:
            mod = curve.modifiers.new(type="CYCLES")
            mod.mode_before = params.get("mode", "REPEAT")
            mod.mode_after = params.get("mode", "REPEAT")
            added += 1
        except (AttributeError, RuntimeError, TypeError):
            continue
    return {"object": obj.name, "cycles_added": added}


@register_tool("animation.clear_keyframes", "animation", "Clear keyframes",
               "Remove F-curves (all or selected data paths) from an object.",
               params={
                   "object": {"type": "string", "required": True},
                   "data_paths": {"type": "list", "default": []},
               })
def clear_keyframes(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    adt = getattr(obj, "animation_data", None)
    action = getattr(adt, "action", None) if adt else None
    if action is None:
        return {"object": obj.name, "removed": 0}
    wanted = set(params.get("data_paths") or [])
    removed = 0
    for curve in list(getattr(action, "fcurves", []) or []):
        if wanted and curve.data_path not in wanted:
            continue
        try:
            action.fcurves.remove(curve)
            removed += 1
        except (AttributeError, RuntimeError, TypeError):
            continue
    return {"object": obj.name, "removed": removed}


@register_tool("animation.list_actions", "animation", "List actions",
               "List animation actions with user counts.",
               params={})
def list_actions(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    return {"actions": [{"name": a.name, "users": a.users,
                         "fcurves": len(getattr(a, "fcurves", []) or [])}
                        for a in bpy.data.actions]}
