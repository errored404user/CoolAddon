"""Project tools: save, import/export, collections."""

from __future__ import annotations

import os
from typing import Any, Dict

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

EXPORT_FORMATS = ("FBX", "OBJ", "GLB", "GLTF", "STL")


def _ensure_folder(path: str) -> str:
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    return path


@register_tool("project.save", "project", "Save project",
               "Save the .blend (current file or a new path).",
               params={"filepath": {"type": "string", "default": ""}})
def project_save(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    path = (params.get("filepath") or "").strip()
    try:
        if path:
            if not path.lower().endswith(".blend"):
                path += ".blend"
            _ensure_folder(path)
            bpy.ops.wm.save_as_mainfile(filepath=path)
        else:
            if not bpy.data.filepath:
                raise ToolError("INVALID_PARAMS",
                                "Blend file is unsaved — provide filepath.")
            bpy.ops.wm.save_mainfile()
            path = bpy.data.filepath
    except ToolError:
        raise
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Save failed: {exc}")
    return {"saved": path or bpy.data.filepath}


@register_tool("project.export", "project", "Export assets",
               "Export FBX / OBJ / GLB / GLTF / STL.",
               params={
                   "format": {"type": "string", "default": "FBX",
                              "choices": list(EXPORT_FORMATS)},
                   "filepath": {"type": "string", "required": True},
                   "selected_only": {"type": "bool", "default": False},
                   "apply_modifiers": {"type": "bool", "default": True},
               })
def project_export(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    fmt = params.get("format", "FBX").upper()
    path = _ensure_folder(str(params["filepath"]))
    roots = {"FBX": ".fbx", "OBJ": ".obj", "GLB": ".glb",
             "GLTF": ".gltf", "STL": ".stl"}
    if not path.lower().endswith(roots[fmt]):
        path += roots[fmt]
    sel = bool(params.get("selected_only", False))
    try:
        if fmt == "FBX":
            bpy.ops.export_scene.fbx(filepath=path, use_selection=sel,
                                     apply_unit_scale=True,
                                     use_mesh_modifiers=params.get("apply_modifiers", True))
        elif fmt == "OBJ":
            bpy.ops.export_scene.obj(filepath=path, use_selection=sel,
                                     use_mesh_modifiers=params.get("apply_modifiers", True))
        elif fmt in ("GLB", "GLTF"):
            bpy.ops.export_scene.gltf(
                filepath=path, use_selection=sel,
                export_format="GLB" if fmt == "GLB" else "GLTF_SEPARATE",
                export_apply=params.get("apply_modifiers", True))
        elif fmt == "STL":
            bpy.ops.export_mesh.stl(filepath=path, use_selection=sel,
                                    use_mesh_modifiers=params.get("apply_modifiers", True))
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Export failed: {exc}")
    size = os.path.getsize(path) if os.path.isfile(path) else 0
    return {"format": fmt, "filepath": path, "bytes": size}


@register_tool("project.import_model", "project", "Import model",
               "Import FBX / OBJ / GLB / GLTF / STL from disk.",
               params={
                   "format": {"type": "string", "default": "FBX",
                              "choices": list(EXPORT_FORMATS)},
                   "filepath": {"type": "string", "required": True},
               })
def project_import(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    path = str(params["filepath"])
    if not os.path.isfile(path):
        raise ToolError("OBJECT_NOT_FOUND", f"File not found: {path}")
    before = set(o.name for o in bpy.data.objects)
    fmt = params.get("format", "FBX").upper()
    try:
        if fmt == "FBX":
            bpy.ops.import_scene.fbx(filepath=path)
        elif fmt == "OBJ":
            bpy.ops.import_scene.obj(filepath=path)
        elif fmt in ("GLB", "GLTF"):
            bpy.ops.import_scene.gltf(filepath=path)
        elif fmt == "STL":
            bpy.ops.import_mesh.stl(filepath=path)
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Import failed: {exc}")
    imported = sorted(set(o.name for o in bpy.data.objects) - before)
    return {"format": fmt, "imported": imported}


@register_tool("project.create_collection", "project", "Create collection",
               "Create (or get) a collection, optionally nested and filled.",
               params={
                   "name": {"type": "string", "required": True},
                   "parent": {"type": "string", "default": ""},
                   "link_objects": {"type": "list", "default": []},
               })
def project_collection(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    parent = params.get("parent") or None
    if parent and parent not in bpy.data.collections:
        raise ToolError("OBJECT_NOT_FOUND", f"Parent collection '{parent}' missing.")
    coll = BU.ensure_collection(params["name"], parent)
    linked = []
    for name in params.get("link_objects") or []:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            coll.objects.link(obj)
            linked.append(name)
        except RuntimeError:
            pass
    return {"collection": coll.name, "linked": linked}


@register_tool("project.move_to_collection", "project", "Move to collection",
               "Move objects into a collection (unlinks others unless kept).",
               params={
                   "collection": {"type": "string", "required": True},
                   "objects": {"type": "list", "default": []},
                   "pattern": {"type": "string", "default": ""},
                   "use_selection": {"type": "bool", "default": False},
                   "keep_others": {"type": "bool", "default": False},
               })
def project_move(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    coll = BU.ensure_collection(params["collection"])
    targets = list(params.get("objects") or [])
    if params.get("pattern"):
        targets += BU.match_names(params["pattern"], [o.name for o in bpy.data.objects])
    if params.get("use_selection"):
        targets += [o.name for o in bpy.context.selected_objects]
    moved = []
    for name in dict.fromkeys(targets):
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        try:
            coll.objects.link(obj)
        except RuntimeError:
            pass
        if not params.get("keep_others"):
            for other in list(obj.users_collection):
                if other != coll:
                    try:
                        other.objects.unlink(obj)
                    except RuntimeError:
                        pass
        moved.append(name)
    return {"collection": coll.name, "moved": moved}
