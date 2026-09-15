"""Optimization tools: analysis, decimation, cleanup, caps."""

from __future__ import annotations

from typing import Any, Dict, List

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU


@register_tool("optimization.analyze", "optimization", "Analyze scene",
               "Report geometry counts, heavy objects, modifiers and suggestions.",
               params={"top_n": {"type": "int", "default": 5}})
def analyze(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    total_verts = total_faces = 0
    per_object: List[Dict[str, Any]] = []
    mod_counts: Dict[str, int] = {}
    heavy_subsurf: List[str] = []
    for obj in bpy.data.objects:
        for mod in getattr(obj, "modifiers", []):
            mod_counts[mod.type] = mod_counts.get(mod.type, 0) + 1
            if mod.type == "SUBSURF":
                try:
                    if max(mod.levels, mod.render_levels) > 2:
                        heavy_subsurf.append(obj.name)
                except AttributeError:
                    pass
        if obj.type == "MESH" and obj.data:
            try:
                verts, faces = len(obj.data.vertices), len(obj.data.polygons)
            except (AttributeError, TypeError):
                continue
            total_verts += verts
            total_faces += faces
            per_object.append({"name": obj.name, "verts": verts, "faces": faces})
    per_object.sort(key=lambda e: e["verts"], reverse=True)
    unused_mats = [m.name for m in bpy.data.materials if m.users == 0]
    unused_groups = [g.name for g in bpy.data.node_groups if g.users == 0]
    images_mb = 0.0
    for img in bpy.data.images:
        try:
            w, h = img.size[0], img.size[1]
            images_mb += w * h * 4 / 1e6
        except (AttributeError, TypeError, IndexError):
            continue
    suggestions = []
    if total_verts > 1_000_000:
        suggestions.append(f"High poly count ({total_verts:,} verts) — consider decimation or LODs.")
    if per_object and per_object[0]["verts"] > 200_000:
        suggestions.append(f"'{per_object[0]['name']}' is very heavy — decimate or retopo.")
    if heavy_subsurf:
        suggestions.append(f"{len(heavy_subsurf)} subsurf modifiers above level 2 — cap with optimization.limit_subsurf.")
    if unused_mats:
        suggestions.append(f"{len(unused_mats)} unused materials — purge with optimization.purge_unused.")
    if unused_groups:
        suggestions.append(f"{len(unused_groups)} unused node groups — purge.")
    if images_mb > 500:
        suggestions.append(f"Textures use ~{images_mb:.0f} MB — downscale large images.")
    if not suggestions:
        suggestions.append("Scene looks healthy — no major issues found.")
    return {"objects": len(bpy.data.objects), "meshes": len(per_object),
            "total_verts": total_verts, "total_faces": total_faces,
            "top_heavy": per_object[:max(1, int(params.get("top_n", 5)))],
            "modifiers": mod_counts, "unused_materials": unused_mats[:20],
            "unused_node_groups": unused_groups[:20],
            "textures_mb": round(images_mb, 1), "suggestions": suggestions}


@register_tool("optimization.decimate_scene", "optimization", "Decimate scene",
               "Decimate heavy meshes matching a pattern (applied).",
               params={
                   "ratio": {"type": "float", "default": 0.5},
                   "pattern": {"type": "string", "default": "*"},
                   "min_verts": {"type": "int", "default": 5000},
               })
def decimate_scene(params: Dict[str, Any]) -> Dict[str, Any]:
    from .modeling_tools import decimate as _decimate
    bpy = require_bpy()
    names = BU.match_names(params.get("pattern", "*"), [o.name for o in bpy.data.objects])
    done, skipped, errors = [], [], []
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "MESH" or not obj.data:
            continue
        try:
            verts = len(obj.data.vertices)
        except (AttributeError, TypeError):
            continue
        if verts < int(params.get("min_verts", 5000)):
            skipped.append(name)
            continue
        try:
            _decimate({"name": name, "ratio": params.get("ratio", 0.5)})
            done.append(name)
        except ToolError as exc:
            errors.append(f"{name}: {exc.message}")
    return {"decimated": done, "skipped_light": len(skipped), "errors": errors}


@register_tool("optimization.remove_doubles", "optimization", "Remove doubles",
               "Weld duplicate verts across meshes (alias with scene-wide default).",
               params={
                   "pattern": {"type": "string", "default": "*"},
                   "distance": {"type": "float", "default": 0.0001},
               })
def remove_doubles(params: Dict[str, Any]) -> Dict[str, Any]:
    from .modeling_tools import merge_by_distance as _merge
    return _merge({"names": [], "pattern": params.get("pattern", "*"),
                   "distance": params.get("distance", 0.0001)})


@register_tool("optimization.limit_subsurf", "optimization", "Cap subsurf levels",
               "Clamp every SUBSURF modifier to a max level (viewport + render).",
               params={"max_levels": {"type": "int", "default": 2}})
def limit_subsurf(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    cap = max(0, min(int(params.get("max_levels", 2)), 6))
    adjusted = []
    for obj in bpy.data.objects:
        for mod in getattr(obj, "modifiers", []):
            if mod.type != "SUBSURF":
                continue
            try:
                if mod.levels > cap or mod.render_levels > cap:
                    mod.levels = min(mod.levels, cap)
                    mod.render_levels = min(mod.render_levels, cap)
                    adjusted.append(f"{obj.name}.{mod.name}")
            except AttributeError:
                continue
    return {"capped_to": cap, "adjusted": adjusted}


@register_tool("optimization.purge_unused", "optimization", "Purge unused data",
               "Remove orphan meshes/materials/images/actions/node groups.",
               params={})
def purge_unused(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    purged = BU.purge_orphans()
    return {"purged": purged, "total": sum(purged.values())}
