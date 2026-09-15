"""Lighting tools: lights, cinematic setups, world/HDRI."""

from __future__ import annotations

import os
from typing import Any, Dict

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

LIGHT_KINDS = ("SUN", "AREA", "POINT", "SPOT")
LIGHT_PRESETS = ("three_point", "rim", "dramatic", "horror", "scifi", "studio", "product")


def _make_light(name: str, kind: str, location, energy: float = 100.0,
                color=None, collection: str = "Lights") -> Any:
    bpy = require_bpy()
    data = bpy.data.lights.new(name=f"{name}_Data", type=kind)
    try:
        data.energy = float(energy)
    except (AttributeError, TypeError):
        pass
    if color is not None:
        try:
            data.color = BU.to_rgba(color, (1, 1, 1, 1))[:3]
        except (AttributeError, TypeError):
            pass
    try:
        data.use_shadow = True
    except (AttributeError, TypeError):
        pass
    obj = bpy.data.objects.new(name, data)
    obj.location = BU.to_vec3(location)
    BU.link_to_collection(obj, collection)
    return obj


@register_tool("lighting.create", "lighting", "Create light",
               "Create a SUN / AREA / POINT / SPOT light.",
               params={
                   "name": {"type": "string", "default": "AI_Light"},
                   "kind": {"type": "string", "default": "AREA",
                            "choices": list(LIGHT_KINDS)},
                   "location": {"type": "list", "default": [3, -3, 5]},
                   "rotation_deg": {"type": "list", "default": None},
                   "energy": {"type": "float", "default": 100.0},
                   "color": {"type": "list", "default": None},
                   "size": {"type": "float", "default": None,
                            "description": "Area size / spot size / shadow soft size"},
                   "spot_blend": {"type": "float", "default": None},
                   "collection": {"type": "string", "default": "Lights"},
               })
def lighting_create(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = _make_light(str(params.get("name", "AI_Light")),
                      params.get("kind", "AREA"),
                      params.get("location", [3, -3, 5]),
                      float(params.get("energy", 100.0)),
                      params.get("color"),
                      params.get("collection") or "Lights")
    if params.get("rotation_deg") is not None:
        obj.rotation_euler = BU.deg_to_rad(params["rotation_deg"])
    data = obj.data
    if params.get("size") is not None:
        size = float(params["size"])
        try:
            if data.type == "AREA":
                data.size = size
            elif data.type == "SPOT":
                data.spot_size = size  # radians
            else:
                data.shadow_soft_size = size
        except (AttributeError, TypeError):
            pass
    if params.get("spot_blend") is not None:
        try:
            data.spot_blend = BU.clamp(params["spot_blend"], 0, 1)
        except (AttributeError, TypeError):
            pass
    return {"name": obj.name, "kind": data.type}


@register_tool("lighting.setup_preset", "lighting", "Lighting preset",
               "Build a cinematic lighting setup around a target point.",
               params={
                   "preset": {"type": "string", "default": "three_point",
                              "choices": list(LIGHT_PRESETS)},
                   "target_point": {"type": "list", "default": [0, 0, 1]},
                   "target": {"type": "string", "default": "",
                              "description": "Object to center on (overrides target_point)"},
                   "energy": {"type": "float", "default": 300.0},
                   "collection": {"type": "string", "default": "Lights"},
               })
def lighting_preset(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    if params.get("target"):
        tgt = BU.require_object(params["target"])
        cx, cy, cz = tgt.matrix_world.translation
    else:
        cx, cy, cz = BU.to_vec3(params.get("target_point"), (0, 0, 1))
    preset = params.get("preset", "three_point")
    energy = float(params.get("energy", 300.0))
    coll = params.get("collection") or "Lights"
    made = []

    def add(name, kind, offset, mult=1.0, color=None):
        obj = _make_light(f"AI_{preset}_{name}", kind,
                          (cx + offset[0], cy + offset[1], cz + offset[2]),
                          energy * mult, color, coll)
        # Aim area/spot lights at the target.
        if kind in ("AREA", "SPOT"):
            from mathutils import Vector
            direction = Vector((cx, cy, cz)) - obj.location
            if direction.length > 1e-6:
                obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        made.append(obj.name)
        return obj

    if preset in ("three_point", "studio"):
        add("Key", "AREA", (4, -4, 4), 1.0)
        add("Fill", "AREA", (-4, -3, 2), 0.35)
        add("Rim", "SPOT", (0, 5, 4), 1.2)
        if preset == "studio":
            add("Top", "AREA", (0, 0, 6), 0.8)
    elif preset == "rim":
        add("Rim", "SPOT", (0, 5, 3), 1.5)
        add("Front", "AREA", (0, -5, 2), 0.15)
    elif preset == "dramatic":
        add("Side", "SPOT", (5, 0, 2), 1.4)
        add("Fill", "POINT", (-3, -2, 1), 0.08)
    elif preset == "horror":
        add("Under", "POINT", (1, -2, -1), 0.5, color=(0.4, 1.0, 0.4))
        add("Rim", "SPOT", (0, 4, 3), 0.8, color=(0.4, 0.6, 1.0))
    elif preset == "scifi":
        add("Cyan", "AREA", (4, -3, 3), 1.0, color=(0.3, 0.9, 1.0))
        add("Magenta", "POINT", (-3, 2, 1), 0.6, color=(1.0, 0.3, 0.8))
        add("Top", "AREA", (0, 0, 5), 0.5, color=(0.7, 0.8, 1.0))
    elif preset == "product":
        add("Top", "AREA", (0, 0, 6), 1.2)
        add("Left", "AREA", (-4, -2, 2), 0.6)
        add("Right", "AREA", (4, -2, 2), 0.6)
    return {"preset": preset, "lights": made}


@register_tool("lighting.set_world", "lighting", "Set world lighting",
               "Configure background color/strength or load an HDRI.",
               params={
                   "background_color": {"type": "list", "default": None},
                   "strength": {"type": "float", "default": None},
                   "hdri_path": {"type": "string", "default": "",
                                 "description": "Absolute path to .hdr/.exr (must exist)"},
               })
def lighting_world(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    scene = BU.ctx_scene()
    if scene.world is None:
        scene.world = bpy.data.worlds.new("AI_World")
    world = scene.world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    bg = nodes.get("Background")
    if bg is None:
        bg = nodes.new("ShaderNodeBackground")
    out = nodes.get("World Output")
    if out is None:
        out = nodes.new("ShaderNodeOutputWorld")
    try:
        links.new(bg.outputs["Background"], out.inputs["Surface"])
    except (AttributeError, KeyError, RuntimeError):
        pass
    changed = []
    hdri = params.get("hdri_path") or ""
    if hdri:
        if not os.path.isfile(hdri):
            raise ToolError("OBJECT_NOT_FOUND", f"HDRI not found: {hdri}")
        try:
            img = bpy.data.images.load(hdri, check_existing=True)
            env = nodes.new("ShaderNodeTexEnvironment")
            env.image = img
            links.new(env.outputs["Color"], bg.inputs["Color"])
            changed.append("hdri")
        except (AttributeError, KeyError, RuntimeError) as exc:
            raise ToolError("TOOL_FAILED", f"Could not load HDRI: {exc}")
    elif params.get("background_color") is not None:
        try:
            bg.inputs["Color"].default_value = BU.to_rgba(params["background_color"])
            changed.append("color")
        except (AttributeError, KeyError, TypeError):
            pass
    if params.get("strength") is not None:
        try:
            bg.inputs["Strength"].default_value = float(params["strength"])
            changed.append("strength")
        except (AttributeError, KeyError, TypeError):
            pass
    return {"world": world.name, "changed": changed}


@register_tool("lighting.list", "lighting", "List lights",
               "List lights with type and energy.",
               params={})
def lighting_list(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    lights = []
    for obj in bpy.data.objects:
        if obj.type == "LIGHT":
            lights.append({"name": obj.name, "kind": obj.data.type,
                           "energy": getattr(obj.data, "energy", None)})
    return {"lights": lights}
