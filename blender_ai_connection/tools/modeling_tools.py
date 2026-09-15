"""Modeling tools: primitives, transforms, modifiers, mesh editing."""

from __future__ import annotations

from typing import Any, Dict

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

PRIMITIVE_KINDS = ("CUBE", "SPHERE_UV", "SPHERE_ICO", "CYLINDER", "CONE",
                   "TORUS", "PLANE", "CIRCLE", "MONKEY", "GRID")

MODIFIER_TYPES = ("SUBSURF", "BEVEL", "BOOLEAN", "MIRROR", "ARRAY", "SOLIDIFY",
                  "DECIMATE", "SMOOTH", "EDGE_SPLIT", "TRIANGULATE", "DISPLACE",
                  "SIMPLE_DEFORM", "SCREW", "SKIN", "REMESH", "WELD", "NODES")


def _mesh_stats(obj) -> Dict[str, int]:
    try:
        mesh = obj.data
        return {"verts": len(mesh.vertices), "edges": len(mesh.edges),
                "faces": len(mesh.polygons)}
    except (AttributeError, TypeError):
        return {}


@register_tool("modeling.create_primitive", "modeling", "Create primitive",
               "Create a mesh primitive with transform, collection and material.",
               params={
                   "kind": {"type": "string", "default": "CUBE",
                            "choices": list(PRIMITIVE_KINDS)},
                   "name": {"type": "string", "default": ""},
                   "location": {"type": "list", "default": [0, 0, 0]},
                   "rotation_deg": {"type": "list", "default": [0, 0, 0]},
                   "scale": {"type": "list", "default": [1, 1, 1]},
                   "size": {"type": "float", "default": 2.0},
                   "collection": {"type": "string", "default": ""},
                   "material": {"type": "string", "default": ""},
               })
def create_primitive(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    BU.set_mode("OBJECT")
    BU.deselect_all()
    kind = params.get("kind", "CUBE")
    loc = BU.to_vec3(params.get("location"), (0, 0, 0))
    rot = BU.deg_to_rad(params.get("rotation_deg"))
    size = float(params.get("size", 2.0))
    try:
        if kind == "CUBE":
            bpy.ops.mesh.primitive_cube_add(size=size, location=loc, rotation=rot)
        elif kind == "SPHERE_UV":
            bpy.ops.mesh.primitive_uv_sphere_add(radius=size / 2, location=loc, rotation=rot)
        elif kind == "SPHERE_ICO":
            bpy.ops.mesh.primitive_ico_sphere_add(radius=size / 2, location=loc, rotation=rot)
        elif kind == "CYLINDER":
            bpy.ops.mesh.primitive_cylinder_add(radius=size / 2, depth=size, location=loc, rotation=rot)
        elif kind == "CONE":
            bpy.ops.mesh.primitive_cone_add(radius1=size / 2, depth=size, location=loc, rotation=rot)
        elif kind == "TORUS":
            bpy.ops.mesh.primitive_torus_add(location=loc, rotation=rot,
                                             major_radius=size / 2, minor_radius=size / 8)
        elif kind == "PLANE":
            bpy.ops.mesh.primitive_plane_add(size=size, location=loc, rotation=rot)
        elif kind == "CIRCLE":
            bpy.ops.mesh.primitive_circle_add(radius=size / 2, location=loc, rotation=rot)
        elif kind == "GRID":
            bpy.ops.mesh.primitive_grid_add(size=size, location=loc, rotation=rot)
        elif kind == "MONKEY":
            bpy.ops.mesh.primitive_monkey_add(size=size, location=loc, rotation=rot)
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Primitive creation failed: {exc}")
    obj = bpy.context.view_layer.objects.active
    if obj is None:
        raise ToolError("TOOL_FAILED", "Primitive created but no active object.")
    if params.get("name"):
        obj.name = str(params["name"])
    obj.scale = BU.to_vec3(params.get("scale"), (1, 1, 1))
    if params.get("collection"):
        BU.link_to_collection(obj, params["collection"])
    if params.get("material"):
        mat = bpy.data.materials.get(params["material"])
        if mat is None:
            raise ToolError("OBJECT_NOT_FOUND",
                            f"Material '{params['material']}' not found.")
        BU.assign_material(obj, mat)
    return {"name": obj.name, "type": obj.type, "stats": _mesh_stats(obj)}


@register_tool("modeling.transform", "modeling", "Transform object",
               "Set (or offset) location / rotation / scale of an object.",
               params={
                   "name": {"type": "string", "required": True},
                   "location": {"type": "list", "default": None},
                   "rotation_deg": {"type": "list", "default": None},
                   "scale": {"type": "list", "default": None},
                   "absolute": {"type": "bool", "default": True},
               })
def transform(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["name"])
    absolute = params.get("absolute", True)
    if params.get("location") is not None:
        vec = BU.to_vec3(params["location"])
        obj.location = vec if absolute else (obj.location[0] + vec[0],
                                             obj.location[1] + vec[1],
                                             obj.location[2] + vec[2])
    if params.get("rotation_deg") is not None:
        vec = BU.deg_to_rad(params["rotation_deg"])
        if absolute:
            obj.rotation_euler = vec
        else:
            obj.rotation_euler = (obj.rotation_euler[0] + vec[0],
                                  obj.rotation_euler[1] + vec[1],
                                  obj.rotation_euler[2] + vec[2])
    if params.get("scale") is not None:
        vec = BU.to_vec3(params.get("scale"))
        obj.scale = vec if absolute else (obj.scale[0] * vec[0],
                                          obj.scale[1] * vec[1],
                                          obj.scale[2] * vec[2])
    return {"name": obj.name, "summary": BU.object_summary(obj)}


@register_tool("modeling.duplicate", "modeling", "Duplicate object",
               "Duplicate an object (optionally linked) with an offset.",
               params={
                   "name": {"type": "string", "required": True},
                   "new_name": {"type": "string", "default": ""},
                   "linked": {"type": "bool", "default": False},
                   "offset": {"type": "list", "default": [0, 0, 0]},
               })
def duplicate(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    src = BU.require_object(params["name"])
    dup = src.copy()
    dup.data = src.data if params.get("linked") else src.data.copy()
    if params.get("new_name"):
        dup.name = str(params["new_name"])
    off = BU.to_vec3(params.get("offset"), (0, 0, 0))
    dup.location = (src.location[0] + off[0], src.location[1] + off[1],
                    src.location[2] + off[2])
    for coll in src.users_collection:
        try:
            coll.objects.link(dup)
        except RuntimeError:
            pass
    if not dup.users_collection:
        BU.link_to_collection(dup)
    BU.set_active(dup)
    return {"name": dup.name, "linked": bool(params.get("linked"))}


@register_tool("modeling.join", "modeling", "Join objects",
               "Join mesh objects into one (first name = active target).",
               params={"names": {"type": "list", "required": True}})
def join(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    names = params.get("names") or []
    if len(names) < 2:
        raise ToolError("INVALID_PARAMS", "join needs at least 2 object names.")
    objs = [BU.require_object(n) for n in names]
    for obj in objs:
        if obj.type != "MESH":
            raise ToolError("TOOL_FAILED", f"'{obj.name}' is {obj.type}, only MESH can join.")
    BU.set_mode("OBJECT")
    BU.select_only(objs)
    BU.set_active(objs[0], select=False)
    try:
        bpy.ops.object.join()
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Join failed: {exc}")
    target = bpy.context.view_layer.objects.active
    return {"name": target.name, "joined": names, "stats": _mesh_stats(target)}


@register_tool("modeling.boolean", "modeling", "Boolean operation",
               "UNION / DIFFERENCE / INTERSECT target with cutter (applied).",
               params={
                   "target": {"type": "string", "required": True},
                   "cutter": {"type": "string", "required": True},
                   "operation": {"type": "string", "default": "DIFFERENCE",
                                 "choices": ["UNION", "DIFFERENCE", "INTERSECT"]},
                   "keep_cutter": {"type": "bool", "default": False},
               })
def boolean(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    target = BU.require_object(params["target"])
    cutter = BU.require_object(params["cutter"])
    if target.type != "MESH" or cutter.type != "MESH":
        raise ToolError("TOOL_FAILED", "Boolean needs two MESH objects.")
    BU.set_mode("OBJECT")
    mod = target.modifiers.new(name="AI_Boolean", type="BOOLEAN")
    mod.operation = params.get("operation", "DIFFERENCE")
    mod.object = cutter
    BU.set_active(target)
    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Boolean apply failed: {exc}")
    if not params.get("keep_cutter"):
        BU.safe_remove_object(cutter)
    return {"name": target.name, "operation": mod.operation if False else params.get("operation"),
            "stats": _mesh_stats(target)}


@register_tool("modeling.add_modifier", "modeling", "Add modifier",
               "Add a modifier with optional settings dict (applied by name).",
               params={
                   "name": {"type": "string", "required": True},
                   "modifier": {"type": "string", "required": True},
                   "settings": {"type": "dict", "default": {}},
               })
def add_modifier(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["name"])
    mtype = str(params.get("modifier", "")).upper()
    if mtype not in MODIFIER_TYPES:
        raise ToolError("INVALID_PARAMS",
                        f"Unsupported modifier '{mtype}'. Supported: {list(MODIFIER_TYPES)}")
    try:
        mod = obj.modifiers.new(name=f"AI_{mtype.title()}", type=mtype)
    except (AttributeError, RuntimeError, TypeError) as exc:
        raise ToolError("TOOL_FAILED", f"Cannot add {mtype} to {obj.type}: {exc}")
    applied, skipped = {}, []
    for key, value in (params.get("settings") or {}).items():
        try:
            current = getattr(mod, key)
            if isinstance(current, bool):
                value = bool(value)
            elif isinstance(current, int) and not isinstance(current, bool):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
            setattr(mod, key, value)
            applied[key] = value
        except (AttributeError, TypeError, ValueError):
            skipped.append(key)
    return {"object": obj.name, "modifier": mod.name, "type": mtype,
            "applied_settings": applied, "skipped_settings": skipped}


@register_tool("modeling.apply_modifier", "modeling", "Apply modifier",
               "Apply a named modifier on an object.",
               params={
                   "name": {"type": "string", "required": True},
                   "modifier": {"type": "string", "required": True},
               })
def apply_modifier(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    obj = BU.require_object(params["name"])
    mod = obj.modifiers.get(params["modifier"])
    if mod is None:
        # Fuzzy fallback: match by prefix (AI_*) or type name.
        want = params["modifier"].lower()
        for candidate in obj.modifiers:
            if want in candidate.name.lower() or want == candidate.type.lower():
                mod = candidate
                break
    if mod is None:
        raise ToolError("OBJECT_NOT_FOUND",
                        f"Modifier '{params['modifier']}' not on '{obj.name}'.",
                        {"available": [m.name for m in obj.modifiers]})
    BU.set_mode("OBJECT")
    BU.set_active(obj)
    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Apply failed: {exc}")
    return {"object": obj.name, "applied": mod.name, "stats": _mesh_stats(obj)}


@register_tool("modeling.bevel", "modeling", "Bevel",
               "Add a (procedural) bevel modifier for hard-surface edges.",
               params={
                   "name": {"type": "string", "required": True},
                   "width": {"type": "float", "default": 0.05},
                   "segments": {"type": "int", "default": 3},
                   "limit_angle": {"type": "float", "default": 30.0},
               })
def bevel(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["name"])
    mod = obj.modifiers.new(name="AI_Bevel", type="BEVEL")
    mod.width = max(0.0001, float(params.get("width", 0.05)))
    mod.segments = max(1, min(int(params.get("segments", 3)), 12))
    try:
        mod.limit_method = "ANGLE"
        mod.angle_limit = __import__("math").radians(float(params.get("limit_angle", 30.0)))
    except (AttributeError, TypeError, ValueError):
        pass
    return {"object": obj.name, "modifier": mod.name}


@register_tool("modeling.subdivide", "modeling", "Subdivide / Subsurf",
               "Modifier subsurf (procedural) or bmesh subdivision (applied).",
               params={
                   "name": {"type": "string", "required": True},
                   "levels": {"type": "int", "default": 2},
                   "method": {"type": "string", "default": "modifier",
                              "choices": ["modifier", "applied"]},
               })
def subdivide(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["name"])
    if obj.type != "MESH":
        raise ToolError("TOOL_FAILED", "Subdivide needs a MESH object.")
    levels = max(1, min(int(params.get("levels", 2)), 4))
    if params.get("method", "modifier") == "modifier":
        mod = obj.modifiers.new(name="AI_Subsurf", type="SUBSURF")
        mod.levels = levels
        mod.render_levels = levels
        return {"object": obj.name, "modifier": mod.name, "levels": levels}
    import bmesh  # Blender-only
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        for _ in range(levels):
            edges = bm.edges[:]
            bmesh.ops.subdivide_edges(bm, edges=edges, cuts=1, use_grid_fill=True)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    return {"object": obj.name, "applied_levels": levels, "stats": _mesh_stats(obj)}


@register_tool("modeling.symmetry", "modeling", "Symmetry (mirror)",
               "Add a mirror modifier on the given axis.",
               params={
                   "name": {"type": "string", "required": True},
                   "axis": {"type": "string", "default": "X",
                            "choices": ["X", "Y", "Z"]},
               })
def symmetry(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["name"])
    mod = obj.modifiers.new(name="AI_Mirror", type="MIRROR")
    axis = params.get("axis", "X")
    mod.use_axis[0] = axis == "X"
    mod.use_axis[1] = axis == "Y"
    mod.use_axis[2] = axis == "Z"
    mod.use_clip = True
    return {"object": obj.name, "modifier": mod.name, "axis": axis}


@register_tool("modeling.set_shade", "modeling", "Shade smooth / flat",
               "Set smooth or flat shading on a mesh object.",
               params={
                   "name": {"type": "string", "required": True},
                   "smooth": {"type": "bool", "default": True},
               })
def set_shade(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["name"])
    if obj.type != "MESH":
        raise ToolError("TOOL_FAILED", "Shade needs a MESH object.")
    try:
        for poly in obj.data.polygons:
            poly.use_smooth = bool(params.get("smooth", True))
        obj.data.update()
    except (AttributeError, RuntimeError) as exc:
        raise ToolError("TOOL_FAILED", f"Shade failed: {exc}")
    return {"name": obj.name, "smooth": bool(params.get("smooth", True))}


@register_tool("modeling.extrude", "modeling", "Extrude faces",
               "Extrude faces along a vector (bmesh, context-safe).",
               params={
                   "name": {"type": "string", "required": True},
                   "vector": {"type": "list", "default": [0, 0, 1]},
                   "faces": {"type": "list", "default": [],
                             "description": "Face indices; empty = all faces"},
               })
def extrude(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    import bmesh
    from mathutils import Vector
    obj = BU.require_object(params["name"])
    if obj.type != "MESH":
        raise ToolError("TOOL_FAILED", "Extrude needs a MESH object.")
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        bm.faces.ensure_lookup_table()
        wanted = params.get("faces") or []
        faces = ([bm.faces[i] for i in wanted if 0 <= i < len(bm.faces)]
                 if wanted else bm.faces[:])
        if not faces:
            raise ToolError("INVALID_PARAMS", "No matching faces to extrude.")
        ret = bmesh.ops.extrude_face_region(bm, geom=faces)
        verts = [e for e in ret["geom"] if isinstance(e, bmesh.types.BMVert)]
        vec = Vector(BU.to_vec3(params.get("vector"), (0, 0, 1)))
        bmesh.ops.translate(bm, verts=verts, vec=vec)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    return {"name": obj.name, "extruded_faces": len(faces), "stats": _mesh_stats(obj)}


@register_tool("modeling.decimate", "modeling", "Decimate",
               "Reduce polygon count by ratio (applied).",
               params={
                   "name": {"type": "string", "required": True},
                   "ratio": {"type": "float", "default": 0.5},
               })
def decimate(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    obj = BU.require_object(params["name"])
    if obj.type != "MESH":
        raise ToolError("TOOL_FAILED", "Decimate needs a MESH object.")
    ratio = BU.clamp(params.get("ratio", 0.5), 0.01, 1.0)
    before = _mesh_stats(obj)
    mod = obj.modifiers.new(name="AI_Decimate", type="DECIMATE")
    mod.ratio = ratio
    BU.set_mode("OBJECT")
    BU.set_active(obj)
    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Decimate failed: {exc}")
    return {"name": obj.name, "ratio": ratio, "before": before,
            "after": _mesh_stats(obj)}


@register_tool("modeling.merge_by_distance", "modeling", "Merge by distance",
               "Weld duplicate vertices on mesh objects (bmesh, context-safe).",
               params={
                   "names": {"type": "list", "default": []},
                   "pattern": {"type": "string", "default": ""},
                   "distance": {"type": "float", "default": 0.0001},
               })
def merge_by_distance(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    import bmesh
    targets = list(params.get("names") or [])
    if params.get("pattern"):
        import bpy as _bpy
        targets += BU.match_names(params["pattern"], [o.name for o in _bpy.data.objects])
    if not targets:
        raise ToolError("INVALID_PARAMS", "Provide names or pattern.")
    merged_total, done = 0, []
    for name in dict.fromkeys(targets):
        obj = BU.find_object(name)
        if obj is None or obj.type != "MESH":
            continue
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        try:
            before = len(bm.verts)
            bmesh.ops.remove_doubles(bm, verts=bm.verts[:],
                                     dist=max(1e-6, float(params.get("distance", 0.0001))))
            merged_total += before - len(bm.verts)
            bm.to_mesh(mesh)
        finally:
            bm.free()
        mesh.update()
        done.append(name)
    return {"objects": done, "merged_verts": merged_total}
