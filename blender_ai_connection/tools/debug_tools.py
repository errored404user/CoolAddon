"""Debug tools: scene diagnosis and safe auto-fixes."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from .base import register_tool, require_bpy
from ..utils import blender_utils as BU


def _collect_issues() -> List[Dict[str, Any]]:
    bpy = require_bpy()
    scene = BU.ctx_scene()
    issues: List[Dict[str, Any]] = []

    cameras = [o for o in bpy.data.objects if o.type == "CAMERA"]
    if not cameras:
        issues.append({"severity": "warning", "category": "scene",
                       "message": "Scene has no camera."})
    elif scene.camera is None:
        issues.append({"severity": "warning", "category": "scene",
                       "message": "No active camera set (scene.camera is None)."})
    if not [o for o in bpy.data.objects if o.type == "LIGHT"]:
        issues.append({"severity": "info", "category": "scene",
                       "message": "Scene has no lights."})
    if scene.frame_end <= scene.frame_start:
        issues.append({"severity": "error", "category": "scene",
                       "message": f"Invalid frame range {scene.frame_start}-{scene.frame_end}."})

    for obj in bpy.data.objects:
        for con in getattr(obj, "constraints", []):
            try:
                needs_target = con.type in ("TRACK_TO", "COPY_LOCATION", "COPY_ROTATION",
                                            "COPY_SCALE", "DAMPED_TRACK", "LOCKED_TRACK",
                                            "STRETCH_TO", "CHILD_OF", "CLAMP_TO")
                if needs_target and getattr(con, "target", None) is None:
                    issues.append({"severity": "error", "category": "constraint",
                                       "object": obj.name,
                                       "message": f"Constraint '{con.name}' ({con.type}) has no target."})
            except (AttributeError, RuntimeError):
                continue
        if obj.type == "ARMATURE":
            for pb in obj.pose.bones:
                for con in pb.constraints:
                    try:
                        if con.type in ("IK", "COPY_LOCATION", "COPY_ROTATION",
                                        "TRACK_TO", "STRETCH_TO") and getattr(con, "target", None) is None:
                            issues.append({"severity": "error", "category": "constraint",
                                               "object": f"{obj.name}:{pb.name}",
                                               "message": f"Bone constraint '{con.name}' has no target."})
                    except (AttributeError, RuntimeError):
                        continue
        for mod in getattr(obj, "modifiers", []):
            try:
                if mod.type == "BOOLEAN" and getattr(mod, "object", None) is None:
                    issues.append({"severity": "error", "category": "modifier",
                                       "object": obj.name,
                                       "message": f"Boolean '{mod.name}' has no target object."})
                if mod.type == "NODES" and getattr(mod, "node_group", None) is None:
                    issues.append({"severity": "error", "category": "modifier",
                                       "object": obj.name,
                                       "message": f"Geometry Nodes '{mod.name}' has no node group."})
                if mod.type == "ARMATURE" and getattr(mod, "object", None) is None:
                    issues.append({"severity": "error", "category": "modifier",
                                       "object": obj.name,
                                       "message": f"Armature '{mod.name}' has no rig object."})
            except (AttributeError, RuntimeError):
                continue
        try:
            sx, sy, sz = obj.scale
            if sx == 0 or sy == 0 or sz == 0:
                issues.append({"severity": "warning", "category": "transform",
                                   "object": obj.name,
                                   "message": f"'{obj.name}' has zero scale {tuple(obj.scale)}."})
        except (AttributeError, TypeError):
            pass

    for img in bpy.data.images:
        try:
            path = (img.filepath or "").strip()
            if path and not img.packed_file and not path.startswith("<"):
                import bpy as _bpy
                abs_path = _bpy.path.abspath(path)
                if not os.path.isfile(abs_path):
                    issues.append({"severity": "error", "category": "assets",
                                       "message": f"Image '{img.name}' missing file: {path}"})
        except (AttributeError, RuntimeError, TypeError):
            continue

    unused = [g.name for g in bpy.data.node_groups if g.users == 0]
    if unused:
        issues.append({"severity": "info", "category": "assets",
                       "message": f"{len(unused)} unused node group(s): {', '.join(unused[:5])}"})
    return issues


def _apply_safe_fixes() -> List[str]:
    bpy = require_bpy()
    scene = BU.ctx_scene()
    fixed: List[str] = []
    if scene.frame_end <= scene.frame_start:
        scene.frame_end = scene.frame_start + 250
        fixed.append(f"Frame range repaired to {scene.frame_start}-{scene.frame_end}.")
    for obj in bpy.data.objects:
        for con in list(getattr(obj, "constraints", [])):
            try:
                if con.type in ("TRACK_TO", "COPY_LOCATION", "COPY_ROTATION",
                                "COPY_SCALE", "DAMPED_TRACK", "LOCKED_TRACK",
                                "STRETCH_TO", "CHILD_OF", "CLAMP_TO") and con.target is None:
                    obj.constraints.remove(con)
                    fixed.append(f"Removed targetless constraint {obj.name}.{con.name}.")
            except (AttributeError, RuntimeError):
                continue
        for mod in list(getattr(obj, "modifiers", [])):
            try:
                if mod.type == "BOOLEAN" and mod.object is None:
                    obj.modifiers.remove(mod)
                    fixed.append(f"Removed broken boolean on {obj.name}.")
                elif mod.type == "NODES" and mod.node_group is None:
                    obj.modifiers.remove(mod)
                    fixed.append(f"Removed empty Geometry Nodes modifier on {obj.name}.")
            except (AttributeError, RuntimeError):
                continue
    purged = BU.purge_orphans()
    total = sum(purged.values())
    if total:
        fixed.append(f"Purged {total} orphan data-block(s).")
    if scene.camera is None:
        cams = [o for o in bpy.data.objects if o.type == "CAMERA"]
        if cams:
            scene.camera = cams[0]
            fixed.append(f"Set active camera to '{cams[0].name}'.")
    return fixed


@register_tool("debug.diagnose", "debug", "Diagnose scene",
               "Inspect the project for broken constraints, modifiers, assets, settings.",
               params={"auto_fix": {"type": "bool", "default": False,
                                    "description": "Apply safe automatic fixes too"}})
def diagnose(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    issues = _collect_issues()
    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    fixed: List[str] = []
    if params.get("auto_fix"):
        fixed = _apply_safe_fixes()
        if fixed:
            issues = _collect_issues()  # re-scan after fixes
            errors = sum(1 for i in issues if i["severity"] == "error")
            warnings = sum(1 for i in issues if i["severity"] == "warning")
    healthy = errors == 0
    return {"healthy": healthy, "issues": issues,
            "counts": {"errors": errors, "warnings": warnings,
                       "info": len(issues) - errors - warnings},
            "fixed": fixed}


@register_tool("debug.fix_common", "debug", "Fix common problems",
               "Apply safe automatic fixes (broken constraints/modifiers, ranges, orphans).",
               params={})
def fix_common(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    fixed = _apply_safe_fixes()
    remaining = _collect_issues()
    errors = sum(1 for i in remaining if i["severity"] == "error")
    return {"fixed": fixed, "remaining_errors": errors,
            "remaining_issues": remaining[:20]}
