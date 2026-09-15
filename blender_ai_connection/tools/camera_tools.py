"""Camera tools: creation, look-at, tracking, sequences."""

from __future__ import annotations

from typing import Any, Dict

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU


def _look_at_euler(cam_loc, target):
    from mathutils import Vector
    direction = Vector(target) - Vector(cam_loc)
    if direction.length < 1e-6:
        raise ToolError("INVALID_PARAMS", "Camera and look-at target coincide.")
    return direction.to_track_quat("-Z", "Y").to_euler()


@register_tool("camera.create", "camera", "Create camera",
               "Create a camera, optionally aimed at a target point/object.",
               params={
                   "name": {"type": "string", "default": "AI_Camera"},
                   "location": {"type": "list", "default": [7, -7, 4]},
                   "rotation_deg": {"type": "list", "default": None},
                   "look_at": {"type": "list", "default": None,
                               "description": "World point [x,y,z] to aim at"},
                   "look_at_object": {"type": "string", "default": "",
                                      "description": "Object name to aim at"},
                   "lens": {"type": "float", "default": 50.0},
                   "set_active": {"type": "bool", "default": True},
                   "collection": {"type": "string", "default": "Cameras"},
               })
def camera_create(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    loc = BU.to_vec3(params.get("location"), (7, -7, 4))
    data = bpy.data.cameras.new(name=f"{params.get('name', 'AI_Camera')}_Data")
    data.lens = BU.clamp(params.get("lens", 50.0), 1.0, 500.0)
    obj = bpy.data.objects.new(str(params.get("name", "AI_Camera")), data)
    obj.location = loc
    target_obj = None
    if params.get("look_at_object"):
        target_obj = BU.require_object(params["look_at_object"])
        obj.rotation_euler = _look_at_euler(loc, target_obj.matrix_world.translation)
    elif params.get("look_at") is not None:
        obj.rotation_euler = _look_at_euler(loc, BU.to_vec3(params["look_at"]))
    elif params.get("rotation_deg") is not None:
        obj.rotation_euler = BU.deg_to_rad(params["rotation_deg"])
    else:
        obj.rotation_euler = _look_at_euler(loc, (0, 0, 1))
    BU.link_to_collection(obj, params.get("collection") or "Cameras")
    if params.get("set_active", True):
        BU.ctx_scene().camera = obj
    return {"name": obj.name, "active": BU.ctx_scene().camera.name}


@register_tool("camera.look_at", "camera", "Aim camera",
               "Rotate a camera to face an object or a world point.",
               params={
                   "camera": {"type": "string", "required": True},
                   "target": {"type": "string", "default": "",
                              "description": "Object name (preferred)"},
                   "target_point": {"type": "list", "default": None},
               })
def camera_look_at(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    cam = BU.require_object(params["camera"])
    if cam.type != "CAMERA":
        raise ToolError("TOOL_FAILED", f"'{cam.name}' is not a camera.")
    if params.get("target"):
        tgt = BU.require_object(params["target"])
        point = tgt.matrix_world.translation
    elif params.get("target_point") is not None:
        point = BU.to_vec3(params["target_point"])
    else:
        raise ToolError("INVALID_PARAMS", "Provide target or target_point.")
    cam.rotation_euler = _look_at_euler(cam.matrix_world.translation, point)
    return {"camera": cam.name}


@register_tool("camera.track_to", "camera", "Track-to constraint",
               "Make a camera continuously track an object.",
               params={
                   "camera": {"type": "string", "required": True},
                   "target": {"type": "string", "required": True},
               })
def camera_track(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    cam = BU.require_object(params["camera"])
    tgt = BU.require_object(params["target"])
    if cam.type != "CAMERA":
        raise ToolError("TOOL_FAILED", f"'{cam.name}' is not a camera.")
    con = cam.constraints.new(type="TRACK_TO")
    con.target = tgt
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    return {"camera": cam.name, "target": tgt.name, "constraint": con.name}


@register_tool("camera.set_active", "camera", "Set active camera",
               "Set the scene's active camera.",
               params={"camera": {"type": "string", "required": True}})
def camera_set_active(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    cam = BU.require_object(params["camera"])
    if cam.type != "CAMERA":
        raise ToolError("TOOL_FAILED", f"'{cam.name}' is not a camera.")
    BU.ctx_scene().camera = cam
    return {"active": cam.name}


@register_tool("camera.create_sequence", "camera", "Camera sequence",
               "Build a multi-shot sequence: cameras + timeline markers + bindings.",
               params={
                   "shots": {"type": "list", "required": True,
                             "description": "[{name?, start, end, location?, look_at_object?, look_at?, lens?}]"},
                   "set_frame_range": {"type": "bool", "default": True},
               })
def camera_sequence(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    shots = params.get("shots") or []
    if not shots:
        raise ToolError("INVALID_PARAMS", "shots must be a non-empty list.")
    scene = BU.ctx_scene()
    made = []
    for i, shot in enumerate(shots):
        if not isinstance(shot, dict) or "start" not in shot or "end" not in shot:
            raise ToolError("INVALID_PARAMS", "Each shot needs {start, end, ...}.")
        name = str(shot.get("name") or f"Shot_{i + 1:02d}")
        loc = BU.to_vec3(shot.get("location"), (7, -7, 4))
        data = bpy.data.cameras.new(name=f"{name}_Data")
        data.lens = BU.clamp(shot.get("lens", 50.0), 1.0, 500.0)
        cam = bpy.data.objects.new(name, data)
        cam.location = loc
        if shot.get("look_at_object"):
            tgt = BU.require_object(shot["look_at_object"])
            cam.rotation_euler = _look_at_euler(loc, tgt.matrix_world.translation)
        elif shot.get("look_at") is not None:
            cam.rotation_euler = _look_at_euler(loc, BU.to_vec3(shot["look_at"]))
        else:
            cam.rotation_euler = _look_at_euler(loc, (0, 0, 1))
        BU.link_to_collection(cam, "Cameras")
        marker = scene.timeline_markers.new(name=name, frame=int(shot["start"]))
        marker.camera_data = cam
        made.append({"camera": cam.name, "marker": marker.name,
                     "start": int(shot["start"]), "end": int(shot["end"])})
    if params.get("set_frame_range", True):
        scene.frame_start = min(s["start"] for s in made)
        scene.frame_end = max(s["end"] for s in made)
    scene.camera = bpy.data.objects[made[0]["camera"]]
    return {"shots": made, "frame_range": [scene.frame_start, scene.frame_end]}


@register_tool("camera.list", "camera", "List cameras",
               "List cameras and the active one.",
               params={})
def camera_list(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    scene = BU.ctx_scene()
    cams = [o.name for o in bpy.data.objects if o.type == "CAMERA"]
    return {"cameras": cams,
            "active": scene.camera.name if scene.camera else None}
