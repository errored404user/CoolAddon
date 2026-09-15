"""Environment tools: terrain, scattering, full presets, atmosphere."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

ENV_PRESETS = ("city", "forest", "desert", "interior", "ruins", "village",
               "lab", "battlefield")


# ---------------------------------------------------------------------------
# Low-level builders (context-safe: bmesh + data API, no operators)
# ---------------------------------------------------------------------------

def _new_mesh_object(name: str, collection: str):
    import bpy
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    obj = bpy.data.objects.new(name, mesh)
    BU.link_to_collection(obj, collection)
    return obj


def _primitive_mesh(kind: str, size: float = 2.0, x_segs: int = 1, y_segs: int = 1):
    import bmesh
    import bpy
    bm = bmesh.new()
    try:
        if kind == "cube":
            bmesh.ops.create_cube(bm, size=size)
        elif kind == "uvsphere":
            bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=size / 2)
        elif kind == "icosphere":
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=size / 2)
        elif kind == "cylinder":
            bmesh.ops.create_cone(bm, cap_ends=True, segments=20,
                                  radius1=size / 2, radius2=size / 2, depth=size)
        elif kind == "cone":
            bmesh.ops.create_cone(bm, cap_ends=True, segments=20,
                                  radius1=size / 2, radius2=0.0, depth=size)
        elif kind == "grid":
            bmesh.ops.create_grid(bm, x_segments=max(1, x_segs),
                                  y_segments=max(1, y_segs), size=size / 2)
        else:
            raise ToolError("INVALID_PARAMS", f"Unknown primitive '{kind}'.")
        mesh = bpy.data.meshes.new(f"AI_{kind}")
        bm.to_mesh(mesh)
    finally:
        bm.free()
    return mesh


def _place(name: str, kind: str, loc, scale=(1, 1, 1), size: float = 2.0,
           collection: str = "Environment", mat: Optional[str] = None,
           shade_smooth: bool = False, rot=None):
    import bpy
    obj = _new_mesh_object(name, collection)
    obj.data = _primitive_mesh(kind, size)
    # Drop the empty placeholder mesh.
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0 and mesh.name.endswith("_Mesh"):
            try:
                bpy.data.meshes.remove(mesh)
            except (AttributeError, RuntimeError, TypeError):
                pass
            break
    obj.location = BU.to_vec3(loc)
    obj.scale = BU.to_vec3(scale, (1, 1, 1))
    if rot is not None:
        obj.rotation_euler = BU.deg_to_rad(rot)
    if shade_smooth and hasattr(obj.data, "polygons"):
        for poly in obj.data.polygons:
            poly.use_smooth = True
    if mat and mat in bpy.data.materials:
        BU.assign_material(obj, bpy.data.materials[mat])
    return obj


def _ensure_simple_material(name: str, color, roughness: float = 0.8,
                            metallic: float = 0.0, emission: Optional[list] = None,
                            emission_strength: float = 0.0) -> str:
    from .material_tools import material_create
    params: Dict[str, Any] = {"name": name, "preset": "principled",
                              "base_color": list(color), "roughness": roughness,
                              "metallic": metallic}
    if emission is not None:
        params.update({"preset": "emissive", "emission_color": list(emission),
                       "emission_strength": emission_strength})
    material_create(params)
    return name


def _displace_terrain(obj, height_scale: float, frequency: float, seed: int) -> None:
    import bmesh
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    try:
        try:
            from mathutils import Vector, noise
            use_noise = True
        except ImportError:
            use_noise = False
        rng = random.Random(seed)
        for vert in bm.verts:
            co = vert.co
            if use_noise:
                sample = Vector((co.x * frequency + seed * 13.7,
                                 co.y * frequency - seed * 7.3, seed * 3.1))
                try:
                    value = noise.fractal(sample, 1.0, 2.0, 4)
                except (AttributeError, TypeError, ValueError):
                    value = rng.uniform(-1, 1)
            else:
                value = rng.uniform(-1, 1)
            vert.co.z += value * height_scale
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    for poly in mesh.polygons:
        poly.use_smooth = True


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@register_tool("environment.create_terrain", "environment", "Create terrain",
               "Procedural noise-displaced terrain grid with smooth shading.",
               params={
                   "name": {"type": "string", "default": "AI_Terrain"},
                   "size": {"type": "float", "default": 40.0},
                   "subdivisions": {"type": "int", "default": 64},
                   "height_scale": {"type": "float", "default": 2.0},
                   "frequency": {"type": "float", "default": 0.08},
                   "seed": {"type": "int", "default": 1},
                   "material": {"type": "string", "default": ""},
                   "collection": {"type": "string", "default": "Environment"},
               })
def create_terrain(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    sub = max(1, min(int(params.get("subdivisions", 64)), 256))
    obj = _place(str(params.get("name", "AI_Terrain")), "grid", (0, 0, 0),
                 size=float(params.get("size", 40.0)), collection=params.get("collection") or "Environment")
    # Rebuild grid at requested resolution.
    obj.data = _primitive_mesh("grid", size=float(params.get("size", 40.0)),
                               x_segs=sub, y_segs=sub)
    _displace_terrain(obj, float(params.get("height_scale", 2.0)),
                      float(params.get("frequency", 0.08)), int(params.get("seed", 1)))
    if params.get("material"):
        import bpy
        mat = bpy.data.materials.get(params["material"])
        if mat:
            BU.assign_material(obj, mat)
    return {"name": obj.name, "verts": len(obj.data.vertices)}


@register_tool("environment.scatter_objects", "environment", "Scatter objects",
               "Duplicate a base object N times over an area (seeded random). "
               "For huge counts prefer nodes.create_geonodes scatter preset.",
               params={
                   "base_object": {"type": "string", "required": True},
                   "count": {"type": "int", "default": 50},
                   "area_size": {"type": "float", "default": 30.0},
                   "collection": {"type": "string", "default": "Environment"},
                   "seed": {"type": "int", "default": 1},
                   "scale_min": {"type": "float", "default": 0.8},
                   "scale_max": {"type": "float", "default": 1.2},
                   "random_rotation": {"type": "bool", "default": True},
                   "linked": {"type": "bool", "default": True,
                              "description": "Linked duplicates (fast, low memory)"},
               })
def scatter(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    base = BU.require_object(params["base_object"])
    count = max(1, min(int(params.get("count", 50)), 2000))
    area = float(params.get("area_size", 30.0))
    rng = random.Random(int(params.get("seed", 1)))
    coll = BU.ensure_collection(params.get("collection") or "Environment")
    smin, smax = float(params.get("scale_min", 0.8)), float(params.get("scale_max", 1.2))
    made = []
    for i in range(count):
        dup = base.copy()
        dup.data = base.data if params.get("linked", True) else base.data.copy()
        dup.name = f"{base.name}_Scatter_{i + 1:04d}"
        s = rng.uniform(min(smin, smax), max(smin, smax))
        dup.location = (rng.uniform(-area / 2, area / 2),
                        rng.uniform(-area / 2, area / 2), base.location.z)
        dup.scale = (base.scale.x * s, base.scale.y * s, base.scale.z * s)
        if params.get("random_rotation", True):
            dup.rotation_euler[2] = rng.uniform(0, 6.2832)
        try:
            coll.objects.link(dup)
        except RuntimeError:
            pass
        made.append(dup.name)
    return {"scattered": len(made), "collection": coll.name}


def _preset_ground(coll: str, preset: str, size: float) -> str:
    colors = {"city": (0.25, 0.25, 0.28), "forest": (0.15, 0.35, 0.12),
              "desert": (0.85, 0.7, 0.45), "interior": (0.4, 0.4, 0.42),
              "ruins": (0.45, 0.43, 0.38), "village": (0.3, 0.45, 0.2),
              "lab": (0.2, 0.22, 0.25), "battlefield": (0.3, 0.27, 0.22)}
    mat = _ensure_simple_material(f"AI_{preset}_Ground",
                                  colors.get(preset, (0.4, 0.4, 0.4)) + (1.0,))
    ground = _place(f"AI_{preset}_Ground", "grid", (0, 0, -0.01), size=size,
                    collection=coll, mat=mat)
    return ground.name


def _preset_builders_runit(name: str, coll: str, rng: random.Random, size: float,
                           out: List[str], mats: Dict[str, str]) -> None:
    if name == "city":
        n, spacing = 5, size / 5
        for ix in range(n):
            for iy in range(n):
                if rng.random() < 0.15:
                    continue
                height = rng.uniform(4, 14)
                x, y = (ix - n / 2 + 0.5) * spacing, (iy - n / 2 + 0.5) * spacing
                out.append(_place(f"AI_City_Tower_{ix}_{iy}", "cube",
                                  (x, y, height / 2),
                                  scale=(spacing * 0.32, spacing * 0.32, height / 2),
                                  collection=coll, mat=mats["wall"]).name)
                out.append(_place(f"AI_City_Windows_{ix}_{iy}", "cube",
                                  (x, y, height * 0.55),
                                  scale=(spacing * 0.33, spacing * 0.33, height * 0.4),
                                  collection=coll, mat=mats["window"]).name)
    elif name == "forest":
        trunk = _place("AI_Tree_Trunk_Proto", "cylinder", (0, 0, 1.0),
                       scale=(0.25, 0.25, 2.0), collection=coll, mat=mats["trunk"])
        fol = _place("AI_Tree_Foliage_Proto", "cone", (0, 0, 3.2),
                     scale=(1.4, 1.4, 2.2), collection=coll, mat=mats["leaf"])
        trunk.hide_viewport = fol.hide_viewport = True
        for i in range(60):
            x, y = rng.uniform(-size / 2, size / 2), rng.uniform(-size / 2, size / 2)
            s = rng.uniform(0.7, 1.6)
            for proto, dz in ((trunk, 0), (fol, 0)):
                dup = proto.copy()
                dup.data = proto.data
                dup.hide_viewport = False
                dup.name = f"{proto.name}_{i:03d}"
                dup.location = (x, y, proto.location.z * s + dz)
                dup.scale = (proto.scale.x * s, proto.scale.y * s, proto.scale.z * s)
                dup.rotation_euler[2] = rng.uniform(0, 6.28)
                BU.ensure_collection(coll).objects.link(dup)
                out.append(dup.name)
    elif name == "desert":
        for i in range(14):
            out.append(_place(f"AI_Rock_{i:02d}", "icosphere",
                              (rng.uniform(-size / 2, size / 2),
                               rng.uniform(-size / 2, size / 2), 0.2),
                              scale=(rng.uniform(0.3, 1.4),) * 3,
                              collection=coll, mat=mats["rock"],
                              shade_smooth=True).name)
        for i in range(8):
            out.append(_place(f"AI_Cactus_{i:02d}", "cylinder",
                              (rng.uniform(-size / 2, size / 2),
                               rng.uniform(-size / 2, size / 2), 1.0),
                              scale=(0.25, 0.25, 1.6),
                              collection=coll, mat=mats["leaf"]).name)
    elif name in ("interior", "lab"):
        wall_mat = mats["wall"]
        room = size * 0.35
        out.append(_place("AI_Room_Floor", "cube", (0, 0, -0.25),
                          scale=(room, room, 0.25), collection=coll, mat=mats["floor"]).name)
        for wx, wy, sx, sy in ((-room, 0, 0.3, room), (room, 0, 0.3, room),
                               (0, -room, room, 0.3), (0, room, room, 0.3)):
            out.append(_place(f"AI_Room_Wall_{wx}_{wy}", "cube", (wx, wy, 2.5),
                              scale=(sx, sy, 2.5), collection=coll, mat=wall_mat).name)
        for i in range(4):
            out.append(_place(f"AI_CeilingLight_{i}", "cube",
                              (-room / 2 + (i % 2) * room, -room / 2 + (i // 2) * room, 4.9),
                              scale=(1.5, 0.3, 0.1), collection=coll, mat=mats["light"]).name)
        for i in range(6):
            x = -room * 0.6 + i * room * 0.24
            out.append(_place(f"AI_Console_{i}", "cube", (x, -room * 0.7, 0.6),
                              scale=(0.8, 0.4, 0.6), collection=coll, mat=mats["metal"]).name)
            out.append(_place(f"AI_ConsoleScreen_{i}", "cube", (x, -room * 0.7 + 0.35, 1.0),
                              scale=(0.7, 0.05, 0.4), collection=coll, mat=mats["screen"]).name)
        for i, (cx, cy) in enumerate([(-room * 0.6, 0), (room * 0.6, 0)]):
            out.append(_place(f"AI_Column_{i}", "cylinder", (cx, cy, 2.5),
                              scale=(0.5, 0.5, 5.0), collection=coll, mat=mats["metal"]).name)
    elif name == "ruins":
        for i in range(10):
            broken = rng.random() < 0.5
            out.append(_place(f"AI_Column_{i:02d}", "cylinder",
                              (rng.uniform(-size / 3, size / 3),
                               rng.uniform(-size / 3, size / 3),
                               rng.uniform(0.5, 2.0) if broken else 2.5),
                              scale=(0.5, 0.5, rng.uniform(1.0, 2.5) if broken else 5.0),
                              collection=coll, mat=mats["stone"],
                              rot=(rng.uniform(-8, 8) if broken else 0,
                                   rng.uniform(-8, 8) if broken else 0, 0)).name)
        for i in range(12):
            out.append(_place(f"AI_Rubble_{i:02d}", "cube",
                              (rng.uniform(-size / 2, size / 2),
                               rng.uniform(-size / 2, size / 2), 0.2),
                              scale=(rng.uniform(0.2, 1.0),) * 3,
                              collection=coll, mat=mats["stone"],
                              rot=(0, 0, rng.uniform(0, 90))).name)
    elif name == "village":
        for i in range(7):
            angle = i / 7 * 6.2832
            x, y = __import__("math").cos(angle) * size * 0.25, __import__("math").sin(angle) * size * 0.25
            out.append(_place(f"AI_Hut_Wall_{i}", "cylinder", (x, y, 1.0),
                              scale=(1.6, 1.6, 2.0), collection=coll, mat=mats["wall"]).name)
            out.append(_place(f"AI_Hut_Roof_{i}", "cone", (x, y, 2.9),
                              scale=(2.2, 2.2, 1.6), collection=coll, mat=mats["roof"]).name)
        out.append(_place("AI_Well", "cylinder", (0, 0, 0.5),
                          scale=(0.8, 0.8, 1.0), collection=coll, mat=mats["stone"]).name)
    elif name == "battlefield":
        for i in range(10):
            out.append(_place(f"AI_Barrier_{i:02d}", "cube",
                              (rng.uniform(-size / 2, size / 2),
                               rng.uniform(-size / 2, size / 2), 0.5),
                              scale=(1.2, 0.3, 0.6), collection=coll, mat=mats["metal"],
                              rot=(0, 0, rng.uniform(0, 90))).name)
        for i in range(20):
            out.append(_place(f"AI_Debris_{i:02d}", "icosphere",
                              (rng.uniform(-size / 2, size / 2),
                               rng.uniform(-size / 2, size / 2), 0.15),
                              scale=(rng.uniform(0.15, 0.6),) * 3,
                              collection=coll, mat=mats["rock"]).name)


@register_tool("environment.create_preset", "environment", "Create environment preset",
               "Generate a complete themed environment (city/forest/desert/…).",
               params={
                   "preset": {"type": "string", "default": "city",
                              "choices": list(ENV_PRESETS)},
                   "size": {"type": "float", "default": 40.0},
                   "seed": {"type": "int", "default": 1},
                   "with_lighting": {"type": "bool", "default": True},
                   "collection": {"type": "string", "default": "Environment"},
               })
def create_preset(params: Dict[str, Any]) -> Dict[str, Any]:
    from .lighting_tools import lighting_create, lighting_preset
    require_bpy()
    preset = params.get("preset", "city")
    size = float(params.get("size", 40.0))
    coll = params.get("collection") or "Environment"
    rng = random.Random(int(params.get("seed", 1)))
    BU.ensure_collection(coll)

    mats = {
        "wall": _ensure_simple_material("AI_Mat_Wall", (0.55, 0.55, 0.58, 1.0), 0.7),
        "window": _ensure_simple_material("AI_Mat_Window", (0.1, 0.1, 0.1, 1.0),
                                          emission=(1.0, 0.85, 0.6, 1.0), emission_strength=2.0),
        "trunk": _ensure_simple_material("AI_Mat_Trunk", (0.3, 0.18, 0.1, 1.0), 0.9),
        "leaf": _ensure_simple_material("AI_Mat_Leaf", (0.12, 0.4, 0.12, 1.0), 0.9),
        "rock": _ensure_simple_material("AI_Mat_Rock", (0.45, 0.43, 0.4, 1.0), 0.95),
        "stone": _ensure_simple_material("AI_Mat_Stone", (0.6, 0.58, 0.52, 1.0), 0.85),
        "roof": _ensure_simple_material("AI_Mat_Roof", (0.5, 0.2, 0.12, 1.0), 0.8),
        "floor": _ensure_simple_material("AI_Mat_Floor", (0.3, 0.3, 0.33, 1.0), 0.5, 0.2),
        "metal": _ensure_simple_material("AI_Mat_Metal", (0.5, 0.52, 0.55, 1.0), 0.35, 0.9),
        "light": _ensure_simple_material("AI_Mat_Light", (1, 1, 1, 1.0),
                                         emission=(1, 1, 1, 1.0), emission_strength=4.0),
        "screen": _ensure_simple_material("AI_Mat_Screen", (0.02, 0.05, 0.08, 1.0),
                                          emission=(0.2, 0.8, 1.0, 1.0), emission_strength=3.0),
    }
    made: List[str] = [_preset_ground(coll, preset, size)]
    _preset_builders_runit(preset, coll, rng, size, made, mats)

    lights: List[str] = []
    if params.get("with_lighting", True):
        mapping = {"city": "studio", "forest": "three_point", "desert": "three_point",
                   "interior": "studio", "ruins": "dramatic", "village": "three_point",
                   "lab": "scifi", "battlefield": "dramatic"}
        lights = lighting_preset({"preset": mapping.get(preset, "three_point"),
                                  "target_point": [0, 0, 2],
                                  "energy": 400.0})["lights"]
        if preset in ("desert", "city", "village", "forest", "ruins", "battlefield"):
            sun = lighting_create({"name": "AI_Sun", "kind": "SUN",
                                   "location": [10, -10, 20], "energy": 5.0})
            lights.append(sun["name"])
    return {"preset": preset, "objects": len(made), "lights": lights,
            "collection": coll}


@register_tool("environment.set_atmosphere", "environment", "Set atmosphere",
               "Add volume-scatter atmosphere to the world for depth/mood.",
               params={
                   "density": {"type": "float", "default": 0.02},
                   "color": {"type": "list", "default": [0.7, 0.75, 0.8, 1.0]},
                   "remove": {"type": "bool", "default": False},
               })
def set_atmosphere(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    scene = BU.ctx_scene()
    if scene.world is None:
        scene.world = bpy.data.worlds.new("AI_World")
    world = scene.world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    out = nodes.get("World Output") or nodes.new("ShaderNodeOutputWorld")
    existing = nodes.get("AI_Atmosphere")
    if params.get("remove"):
        if existing:
            nodes.remove(existing)
        return {"world": world.name, "atmosphere": False}
    scatter = existing or nodes.new("ShaderNodeVolumeScatter")
    scatter.name = "AI_Atmosphere"
    try:
        scatter.inputs["Color"].default_value = BU.to_rgba(params.get("color"))
        scatter.inputs["Density"].default_value = max(0.0, float(params.get("density", 0.02)))
        links.new(scatter.outputs["Volume"], out.inputs["Volume"])
    except (AttributeError, KeyError, RuntimeError) as exc:
        raise ToolError("TOOL_FAILED", f"Atmosphere setup failed: {exc}")
    return {"world": world.name, "atmosphere": True,
            "density": float(params.get("density", 0.02))}
