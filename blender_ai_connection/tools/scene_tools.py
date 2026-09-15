"""Scene tools: inspect, clear, organize, select, delete."""

from __future__ import annotations

from typing import Any, Dict

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU


@register_tool("scene.inspect", "scene", "Inspect scene",
               "Full scene summary: objects, collections, materials, cameras, "
               "lights, armatures, selection, render settings.",
               params={
                   "object_limit": {"type": "int", "default": 200,
                                    "description": "Max objects to list in detail"},
               })
def scene_inspect(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    scene = BU.ctx_scene()
    limit = max(1, min(int(params.get("object_limit", 200)), 2000))
    objects = list(bpy.data.objects)
    by_type: Dict[str, int] = {}
    for obj in objects:
        by_type[obj.type] = by_type.get(obj.type, 0) + 1
    render = scene.render
    return {
        "scene": scene.name,
        "objects_total": len(objects),
        "objects_by_type": by_type,
        "objects": [BU.object_summary(o) for o in objects[:limit]],
        "truncated": len(objects) > limit,
        "collections": sorted(c.name for c in bpy.data.collections),
        "materials": sorted(m.name for m in bpy.data.materials),
        "cameras": sorted(o.name for o in objects if o.type == "CAMERA"),
        "active_camera": scene.camera.name if scene.camera else None,
        "lights": sorted(o.name for o in objects if o.type == "LIGHT"),
        "armatures": sorted(o.name for o in objects if o.type == "ARMATURE"),
        "selected": sorted(o.name for o in bpy.context.selected_objects),
        "active": (bpy.context.view_layer.objects.active.name
                   if bpy.context.view_layer.objects.active else None),
        "frame": {"start": scene.frame_start, "end": scene.frame_end,
                  "current": scene.frame_current, "fps": render.fps},
        "render": {"engine": render.engine,
                   "resolution": [render.resolution_x, render.resolution_y],
                   "samples": getattr(scene.cycles, "samples", None)
                   if render.engine == "CYCLES" else None,
                   "filepath": render.filepath},
        "node_groups": len(bpy.data.node_groups),
        "actions": sorted(a.name for a in bpy.data.actions),
    }


@register_tool("scene.clear", "scene", "Clear scene",
               "Delete scene content. Requires confirm=true as a safety lock.",
               params={
                   "mode": {"type": "string", "default": "objects",
                            "choices": ["objects", "meshes", "all"],
                            "description": "objects: delete objects; "
                                           "meshes: mesh objects only; all: objects + orphan data"},
                   "protect": {"type": "list", "default": [],
                               "description": "Object names to keep"},
                   "confirm": {"type": "bool", "required": True,
                               "description": "Must be true to run"},
               })
def scene_clear(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    if params.get("confirm") is not True:
        raise ToolError("INVALID_PARAMS", "scene.clear requires confirm=true.")
    BU.set_mode("OBJECT")
    protect = set(params.get("protect") or [])
    mode = params.get("mode", "objects")
    deleted = 0
    for obj in list(bpy.data.objects):
        if obj.name in protect:
            continue
        if mode == "meshes" and obj.type != "MESH":
            continue
        BU.safe_remove_object(obj)
        deleted += 1
    purged = BU.purge_orphans() if mode == "all" else {}
    return {"deleted": deleted, "protected": sorted(protect), "purged": purged}


@register_tool("scene.organize", "scene", "Organize scene",
               "Move objects into collections grouped by type.",
               params={})
def scene_organize(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    mapping = {"MESH": "Meshes", "CURVE": "Curves", "CAMERA": "Cameras",
               "LIGHT": "Lights", "ARMATURE": "Armatures",
               "EMPTY": "Empties", "FONT": "Texts"}
    counts: Dict[str, int] = {}
    for obj in list(bpy.data.objects):
        coll_name = mapping.get(obj.type, "Others")
        coll = BU.ensure_collection(coll_name)
        if obj.name not in coll.objects:
            try:
                coll.objects.link(obj)
                counts[coll_name] = counts.get(coll_name, 0) + 1
            except RuntimeError:
                pass
        # Unlink from the master collection to keep the outliner tidy.
        master = bpy.context.scene.collection
        if obj.name in master.objects and len(obj.users_collection) > 1:
            try:
                master.objects.unlink(obj)
            except RuntimeError:
                pass
    return {"grouped": counts}


@register_tool("scene.select", "scene", "Select objects",
               "Select objects by wildcard pattern and/or type.",
               params={
                   "pattern": {"type": "string", "default": "*"},
                   "type": {"type": "string", "default": "",
                            "description": "Blender object type filter, e.g. MESH"},
                   "extend": {"type": "bool", "default": False},
               })
def scene_select(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    names = [o.name for o in bpy.data.objects]
    matched = BU.match_names(params.get("pattern", "*"), names)
    want_type = (params.get("type") or "").upper()
    selected = []
    if not params.get("extend"):
        BU.deselect_all()
    for name in matched:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        if want_type and obj.type != want_type:
            continue
        obj.select_set(True)
        selected.append(name)
    if selected:
        BU.set_active(bpy.data.objects[selected[0]])
    return {"selected": selected, "count": len(selected)}


@register_tool("scene.delete", "scene", "Delete objects",
               "Delete objects by explicit names and/or wildcard pattern.",
               params={
                   "names": {"type": "list", "default": []},
                   "pattern": {"type": "string", "default": ""},
               })
def scene_delete(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    BU.set_mode("OBJECT")
    targets = list(params.get("names") or [])
    if params.get("pattern"):
        targets += BU.match_names(params["pattern"],
                                  [o.name for o in bpy.data.objects])
    deleted, missing = [], []
    for name in dict.fromkeys(targets):  # de-dupe, keep order
        obj = bpy.data.objects.get(name)
        if obj is None:
            missing.append(name)
            continue
        BU.safe_remove_object(obj)
        deleted.append(name)
    return {"deleted": deleted, "missing": missing}


@register_tool("scene.set_active", "scene", "Set active object",
               "Set the active (and selected) object by name.",
               params={"name": {"type": "string", "required": True}})
def scene_set_active(params: Dict[str, Any]) -> Dict[str, Any]:
    obj = BU.require_object(params["name"])
    BU.set_active(obj)
    return {"active": obj.name, "summary": BU.object_summary(obj)}
