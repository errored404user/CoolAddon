"""Procedural tools: parametric buildings, stairs, array distribution."""

from __future__ import annotations

from typing import Any, Dict, List

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU


@register_tool("procedural.create_building", "procedural", "Create building",
               "Parametric multi-floor building with modifier-based window grids.",
               params={
                   "name": {"type": "string", "default": "AI_Building"},
                   "width": {"type": "float", "default": 10.0},
                   "depth": {"type": "float", "default": 8.0},
                   "floors": {"type": "int", "default": 5},
                   "floor_height": {"type": "float", "default": 3.0},
                   "location": {"type": "list", "default": [0, 0, 0]},
                   "wall_material": {"type": "string", "default": ""},
                   "window_material": {"type": "string", "default": ""},
                   "collection": {"type": "string", "default": "Environment"},
               })
def create_building(params: Dict[str, Any]) -> Dict[str, Any]:
    from .material_tools import material_create
    from .modeling_tools import create_primitive

    require_bpy()
    name = str(params.get("name", "AI_Building"))
    width = float(params.get("width", 10.0))
    depth = float(params.get("depth", 8.0))
    floors = max(1, min(int(params.get("floors", 5)), 60))
    floor_h = max(1.0, float(params.get("floor_height", 3.0)))
    bx, by, bz = BU.to_vec3(params.get("location"), (0, 0, 0))
    coll = params.get("collection") or "Environment"
    total_h = floors * floor_h
    parts: List[str] = []

    wall_mat = params.get("wall_material") or f"{name}_Wall"
    win_mat = params.get("window_material") or f"{name}_Windows"
    material_create({"name": wall_mat, "preset": "principled",
                     "base_color": [0.6, 0.6, 0.62, 1.0], "roughness": 0.8})
    material_create({"name": win_mat, "preset": "emissive",
                     "emission_color": [1.0, 0.85, 0.6, 1.0],
                     "emission_strength": 1.5,
                     "base_color": [0.1, 0.12, 0.15, 1.0]})

    body = create_primitive({"kind": "CUBE", "name": f"{name}_Body",
                             "location": [bx, by, bz + total_h / 2],
                             "scale": [width / 2, depth / 2, total_h / 2],
                             "collection": coll, "material": wall_mat})["name"]
    parts.append(body)
    roof = create_primitive({"kind": "CUBE", "name": f"{name}_Roof",
                             "location": [bx, by, bz + total_h + 0.15],
                             "scale": [width / 2 + 0.3, depth / 2 + 0.3, 0.15],
                             "collection": coll, "material": wall_mat})["name"]
    parts.append(roof)

    # Window grids: one plane + ARRAY x floors, duplicated per facade.
    cols_front = max(2, int(width / 2.0))
    for facade, (px, py, rot_z, cols) in {
        "Front": ((0, depth / 2 + 0.03, 0), 0, cols_front),
        "Back": ((0, -depth / 2 - 0.03, 0), 180, cols_front),
        "Left": ((-width / 2 - 0.03, 0, 0), 90, max(2, int(depth / 2.0))),
        "Right": ((width / 2 + 0.03, 0, 0), -90, max(2, int(depth / 2.0))),
    }.items():
        grid = create_primitive({"kind": "PLANE", "name": f"{name}_Win_{facade}",
                                 "location": [bx + px[0], by + px[1], bz + floor_h / 2],
                                 "rotation_deg": [0, 0, rot_z],
                                 "scale": [0.7, 0.7, 1.0], "size": 1.2,
                                 "collection": coll, "material": win_mat})["name"]
        obj = BU.require_object(grid)
        arr_x = obj.modifiers.new("AI_Win_X", "ARRAY")
        arr_x.count = cols
        arr_x.relative_offset_displace = (2.2, 0, 0)
        arr_y = obj.modifiers.new("AI_Win_Y", "ARRAY")
        arr_y.count = floors
        arr_y.relative_offset_displace = (0, 0, 0)
        arr_y.constant_offset_displace = (0, 0, floor_h)
        # Center the grid on the facade.
        obj.location.x -= (cols - 1) * 1.32 if facade in ("Front", "Back") else 0
        parts.append(grid)
    return {"building": name, "parts": parts, "floors": floors,
            "height": total_h}


@register_tool("procedural.create_stairs", "procedural", "Create stairs",
               "Parametric staircase (steps joined into one mesh).",
               params={
                   "name": {"type": "string", "default": "AI_Stairs"},
                   "steps": {"type": "int", "default": 10},
                   "width": {"type": "float", "default": 2.0},
                   "step_height": {"type": "float", "default": 0.25},
                   "step_depth": {"type": "float", "default": 0.4},
                   "location": {"type": "list", "default": [0, 0, 0]},
                   "collection": {"type": "string", "default": "Environment"},
               })
def create_stairs(params: Dict[str, Any]) -> Dict[str, Any]:
    from .modeling_tools import create_primitive, join

    require_bpy()
    name = str(params.get("name", "AI_Stairs"))
    steps = max(1, min(int(params.get("steps", 10)), 200))
    width = float(params.get("width", 2.0))
    step_h = float(params.get("step_height", 0.25))
    step_d = float(params.get("step_depth", 0.4))
    bx, by, bz = BU.to_vec3(params.get("location"), (0, 0, 0))
    coll = params.get("collection") or "Environment"
    names = []
    for i in range(steps):
        names.append(create_primitive(
            {"kind": "CUBE", "name": f"{name}_Step_{i:03d}",
             "location": [bx, by + i * step_d, bz + i * step_h + step_h / 2],
             "scale": [width / 2, step_d / 2, step_h / 2],
             "collection": coll})["name"])
    # Join in chunks to stay fast and context-safe.
    target = names[0]
    for chunk_start in range(1, len(names), 20):
        chunk = [target] + names[chunk_start:chunk_start + 20]
        target = join({"names": chunk})["name"]
    obj = BU.require_object(target)
    obj.name = name
    return {"stairs": name, "steps": steps,
            "total_height": steps * step_h, "total_depth": steps * step_d}


@register_tool("procedural.array_distribute", "procedural", "Array distribute",
               "Add a configured ARRAY modifier for repeating structures.",
               params={
                   "object": {"type": "string", "required": True},
                   "count": {"type": "int", "default": 5},
                   "relative_offset": {"type": "list", "default": [1.5, 0, 0]},
                   "constant_offset": {"type": "list", "default": [0, 0, 0]},
                   "merge": {"type": "bool", "default": False},
               })
def array_distribute(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    mod = obj.modifiers.new("AI_Array", "ARRAY")
    mod.count = max(1, min(int(params.get("count", 5)), 1000))
    mod.relative_offset_displace = BU.to_vec3(params.get("relative_offset"), (1.5, 0, 0))
    mod.constant_offset_displace = BU.to_vec3(params.get("constant_offset"), (0, 0, 0))
    mod.use_merge_vertices = bool(params.get("merge", False))
    return {"object": obj.name, "modifier": mod.name, "count": mod.count}
