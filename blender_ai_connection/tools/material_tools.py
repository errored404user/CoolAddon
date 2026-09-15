"""Material tools: PBR presets, node setups, assignment."""

from __future__ import annotations

from typing import Any, Dict

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

MATERIAL_PRESETS = (
    "principled", "metal", "brushed_metal", "plastic", "glass", "fabric",
    "wood", "stone", "skin", "ceramic", "emissive", "scifi_glow", "stylized",
)


def _set_input(bsdf, candidates, value) -> bool:
    """Try multiple socket names (Blender 3.x vs 4.x differences)."""
    if isinstance(candidates, str):
        candidates = [candidates]
    for name in candidates:
        sock = bsdf.inputs.get(name)
        if sock is not None:
            try:
                if hasattr(sock, "default_value"):
                    if hasattr(sock.default_value, "__len__") and not isinstance(value, (str, bytes)):
                        try:
                            sock.default_value = tuple(value)
                        except (TypeError, ValueError):
                            sock.default_value = value
                    else:
                        sock.default_value = value
                    return True
            except (AttributeError, TypeError, ValueError):
                continue
    return False


def _add_noise_bump(mat, scale: float = 5.0, strength: float = 0.3,
                    detail: str = "noise"):
    """Add a Noise/Voronoi -> Bump chain into the Principled Normal input."""
    bsdf = BU.principled_bsdf(mat)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    tex = nodes.new("ShaderNodeTexNoise" if detail == "noise" else "ShaderNodeTexVoronoi")
    tex.location = (-600, -200)
    try:
        tex.inputs["Scale"].default_value = scale
    except (AttributeError, KeyError, TypeError):
        pass
    bump = nodes.new("ShaderNodeBump")
    bump.location = (-300, -200)
    try:
        bump.inputs["Strength"].default_value = strength
    except (AttributeError, KeyError, TypeError):
        pass
    out = "Fac" if "Fac" in tex.outputs else list(tex.outputs)[0].name
    links.new(tex.outputs[out], bump.inputs["Height"])
    if "Normal" in bsdf.inputs:
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _apply_preset(mat, preset: str, p: Dict[str, Any]) -> None:
    bpy = require_bpy()
    bsdf = BU.principled_bsdf(mat)
    base = BU.to_rgba(p.get("base_color"), (0.8, 0.8, 0.8, 1.0))
    _set_input(bsdf, "Base Color", base)
    _set_input(bsdf, "Metallic", BU.clamp(p.get("metallic", 0.0), 0, 1))
    _set_input(bsdf, "Roughness", BU.clamp(p.get("roughness", 0.5), 0, 1))

    if preset == "metal":
        _set_input(bsdf, "Metallic", 1.0)
        _set_input(bsdf, "Roughness", p.get("roughness", 0.3))
    elif preset == "brushed_metal":
        _set_input(bsdf, "Metallic", 1.0)
        _set_input(bsdf, "Roughness", p.get("roughness", 0.45))
        _add_noise_bump(mat, scale=40.0, strength=0.08)
    elif preset == "plastic":
        _set_input(bsdf, ["Specular", "Specular IOR Level"], 0.5)
    elif preset == "glass":
        _set_input(bsdf, ["Transmission Weight", "Transmission"], 1.0)
        _set_input(bsdf, "Roughness", p.get("roughness", 0.05))
        _set_input(bsdf, "IOR", 1.45)
        try:
            mat.blend_method = "BLEND"
        except (AttributeError, TypeError):
            pass
    elif preset == "fabric":
        _set_input(bsdf, "Roughness", 0.9)
        _set_input(bsdf, ["Sheen Weight", "Sheen"], 0.6)
        _add_noise_bump(mat, scale=25.0, strength=0.15)
    elif preset == "wood":
        if p.get("base_color") is None:
            _set_input(bsdf, "Base Color", (0.35, 0.2, 0.1, 1.0))
        _add_noise_bump(mat, scale=3.0, strength=0.25)
    elif preset == "stone":
        if p.get("base_color") is None:
            _set_input(bsdf, "Base Color", (0.45, 0.45, 0.47, 1.0))
        _set_input(bsdf, "Roughness", 0.85)
        _add_noise_bump(mat, scale=8.0, strength=0.4, detail="voronoi")
    elif preset == "skin":
        if p.get("base_color") is None:
            _set_input(bsdf, "Base Color", (0.85, 0.6, 0.5, 1.0))
        _set_input(bsdf, ["Subsurface Weight", "Subsurface"], 0.4)
        _set_input(bsdf, ["Subsurface Color", "Subsurface Color"], (0.7, 0.25, 0.2, 1.0))
    elif preset == "ceramic":
        _set_input(bsdf, "Roughness", 0.15)
        _set_input(bsdf, ["Coat Weight", "Clearcoat"], 0.5)
    elif preset in ("emissive", "scifi_glow"):
        glow = BU.to_rgba(p.get("emission_color"),
                          (0.1, 0.8, 1.0, 1.0) if preset == "scifi_glow" else (1, 1, 1, 1))
        _set_input(bsdf, ["Emission Color", "Emission"], glow)
        _set_input(bsdf, "Emission Strength",
                   float(p.get("emission_strength", 5.0 if preset == "scifi_glow" else 2.0)))
        if preset == "scifi_glow":
            _set_input(bsdf, "Base Color", (0.02, 0.03, 0.04, 1.0))
            _set_input(bsdf, "Metallic", 0.8)
            _set_input(bsdf, "Roughness", 0.35)
    elif preset == "stylized":
        _set_input(bsdf, "Roughness", 0.6)
        _set_input(bsdf, ["Specular", "Specular IOR Level"], 0.3)

    if p.get("alpha") is not None:
        _set_input(bsdf, "Alpha", BU.clamp(p["alpha"], 0, 1))
        try:
            mat.blend_method = "BLEND" if float(p["alpha"]) < 1.0 else "OPAQUE"
        except (AttributeError, TypeError, ValueError):
            pass


@register_tool("material.list", "material", "List materials",
               "List all materials with user counts.",
               params={})
def material_list(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    return {"materials": [
        {"name": m.name, "users": m.users, "use_nodes": m.use_nodes}
        for m in bpy.data.materials]}


@register_tool("material.create", "material", "Create material",
               "Create a PBR material from a preset with optional overrides.",
               params={
                   "name": {"type": "string", "required": True},
                   "preset": {"type": "string", "default": "principled",
                              "choices": list(MATERIAL_PRESETS)},
                   "base_color": {"type": "list", "default": None,
                                  "description": "RGB or RGBA 0-1"},
                   "metallic": {"type": "float", "default": None},
                   "roughness": {"type": "float", "default": None},
                   "emission_color": {"type": "list", "default": None},
                   "emission_strength": {"type": "float", "default": None},
                   "alpha": {"type": "float", "default": None},
               })
def material_create(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    name = str(params.get("name", "AI_Material"))
    preset = params.get("preset", "principled")
    clean = {k: v for k, v in params.items() if v is not None}
    mat = BU.ensure_material(name)
    _apply_preset(mat, preset, clean)
    return {"name": mat.name, "preset": preset}


@register_tool("material.assign", "material", "Assign material",
               "Assign a material to objects (names / pattern / selected / active).",
               params={
                   "material": {"type": "string", "required": True},
                   "objects": {"type": "list", "default": []},
                   "pattern": {"type": "string", "default": ""},
                   "use_selection": {"type": "bool", "default": False},
               })
def material_assign(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    mat = bpy.data.materials.get(params["material"])
    if mat is None:
        raise ToolError("OBJECT_NOT_FOUND",
                        f"Material '{params['material']}' not found.")
    targets = list(params.get("objects") or [])
    if params.get("pattern"):
        targets += BU.match_names(params["pattern"], [o.name for o in bpy.data.objects])
    if params.get("use_selection"):
        targets += [o.name for o in bpy.context.selected_objects]
    if not targets:
        active = bpy.context.view_layer.objects.active
        if active is None:
            raise ToolError("INVALID_PARAMS",
                            "No target: pass objects/pattern or select something.")
        targets = [active.name]
    assigned, skipped = [], []
    for name in dict.fromkeys(targets):
        obj = bpy.data.objects.get(name)
        if obj is None:
            skipped.append(name)
            continue
        try:
            BU.assign_material(obj, mat)
            assigned.append(name)
        except ToolError:
            skipped.append(name)
    return {"material": mat.name, "assigned": assigned, "skipped": skipped}


@register_tool("material.set_principled", "material", "Edit Principled values",
               "Modify Base Color / Metallic / Roughness / Emission / Alpha.",
               params={
                   "material": {"type": "string", "required": True},
                   "base_color": {"type": "list", "default": None},
                   "metallic": {"type": "float", "default": None},
                   "roughness": {"type": "float", "default": None},
                   "emission_color": {"type": "list", "default": None},
                   "emission_strength": {"type": "float", "default": None},
                   "alpha": {"type": "float", "default": None},
               })
def material_set(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    mat = bpy.data.materials.get(params["material"])
    if mat is None:
        raise ToolError("OBJECT_NOT_FOUND",
                        f"Material '{params['material']}' not found.")
    bsdf = BU.principled_bsdf(mat)
    changed = []
    mapping = (("base_color", "Base Color", lambda v: BU.to_rgba(v)),
               ("metallic", "Metallic", lambda v: BU.clamp(v, 0, 1)),
               ("roughness", "Roughness", lambda v: BU.clamp(v, 0, 1)),
               ("emission_color", ["Emission Color", "Emission"], lambda v: BU.to_rgba(v)),
               ("emission_strength", "Emission Strength", float),
               ("alpha", "Alpha", lambda v: BU.clamp(v, 0, 1)))
    for key, sock, conv in mapping:
        if params.get(key) is not None:
            if _set_input(bsdf, sock, conv(params[key])):
                changed.append(key)
    return {"material": mat.name, "changed": changed}


@register_tool("material.create_node_setup", "material", "Node setup",
               "Build a small procedural shader network on a material.",
               params={
                   "material": {"type": "string", "required": True},
                   "setup": {"type": "string", "default": "noise_bump",
                             "choices": ["noise_bump", "checker", "voronoi_cracks",
                                         "gradient"]},
                   "scale": {"type": "float", "default": 5.0},
                   "strength": {"type": "float", "default": 0.3},
               })
def material_nodes(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    mat = bpy.data.materials.get(params["material"])
    if mat is None:
        raise ToolError("OBJECT_NOT_FOUND",
                        f"Material '{params['material']}' not found.")
    setup = params.get("setup", "noise_bump")
    scale = float(params.get("scale", 5.0))
    if setup == "noise_bump":
        _add_noise_bump(mat, scale=scale, strength=float(params.get("strength", 0.3)))
    elif setup == "voronoi_cracks":
        _add_noise_bump(mat, scale=scale, strength=float(params.get("strength", 0.5)),
                        detail="voronoi")
    else:
        bsdf = BU.principled_bsdf(mat)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        tex = nodes.new("ShaderNodeTexChecker" if setup == "checker" else "ShaderNodeTexGradient")
        tex.location = (-400, 200)
        try:
            tex.inputs["Scale"].default_value = scale
        except (AttributeError, KeyError, TypeError):
            pass
        try:
            links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        except (AttributeError, KeyError, RuntimeError) as exc:
            raise ToolError("TOOL_FAILED", f"Could not link nodes: {exc}")
    return {"material": mat.name, "setup": setup}


@register_tool("material.remove", "material", "Remove material",
               "Delete a material data-block.",
               params={"name": {"type": "string", "required": True}})
def material_remove(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    mat = bpy.data.materials.get(params["name"])
    if mat is None:
        raise ToolError("OBJECT_NOT_FOUND", f"Material '{params['name']}' not found.")
    try:
        bpy.data.materials.remove(mat)
    except (AttributeError, RuntimeError) as exc:
        raise ToolError("TOOL_FAILED", f"Could not remove material: {exc}")
    return {"removed": params["name"]}
