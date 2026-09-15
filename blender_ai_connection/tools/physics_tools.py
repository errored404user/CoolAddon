"""Physics tools: rigid bodies, cloth, collision, forces, baking."""

from __future__ import annotations

from typing import Any, Dict

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

BODY_TYPES = ("ACTIVE", "PASSIVE")
COLLISION_SHAPES = ("CONVEX_HULL", "MESH", "BOX", "SPHERE", "CAPSULE", "CYLINDER", "CONE")
CLOTH_PRESETS = ("COTTON", "DENIM", "LEATHER", "RUBBER", "SILK")
FORCE_KINDS = ("WIND", "TURBULENCE", "VORTEX", "MAGNET", "DRAG", "BOID")


def _ensure_rigidbody_world():
    bpy = require_bpy()
    scene = BU.ctx_scene()
    if scene.rigidbody_world is None:
        BU.set_mode("OBJECT")
        try:
            bpy.ops.rigidbody.world_add()
        except RuntimeError as exc:
            raise ToolError("TOOL_FAILED",
                            f"Could not create rigid-body world: {exc}")
    return scene.rigidbody_world


@register_tool("physics.add_rigid_body", "physics", "Add rigid body",
               "Make objects rigid bodies (active/passive) with physical properties.",
               params={
                   "objects": {"type": "list", "default": []},
                   "pattern": {"type": "string", "default": ""},
                   "use_selection": {"type": "bool", "default": False},
                   "body_type": {"type": "string", "default": "ACTIVE",
                                 "choices": list(BODY_TYPES)},
                   "mass": {"type": "float", "default": 1.0},
                   "friction": {"type": "float", "default": 0.5},
                   "bounciness": {"type": "float", "default": 0.0},
                   "collision_shape": {"type": "string", "default": "CONVEX_HULL",
                                       "choices": list(COLLISION_SHAPES)},
               })
def physics_rigid(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    _ensure_rigidbody_world()
    targets = list(params.get("objects") or [])
    if params.get("pattern"):
        targets += BU.match_names(params["pattern"], [o.name for o in bpy.data.objects])
    if params.get("use_selection"):
        targets += [o.name for o in bpy.context.selected_objects]
    if not targets:
        raise ToolError("INVALID_PARAMS", "No targets: pass objects/pattern or select some.")
    done, skipped = [], []
    for name in dict.fromkeys(targets):
        obj = bpy.data.objects.get(name)
        if obj is None:
            skipped.append(name)
            continue
        BU.set_mode("OBJECT")
        BU.set_active(obj)
        try:
            if getattr(obj, "rigid_body", None) is None:
                bpy.ops.rigidbody.object_add(type=params.get("body_type", "ACTIVE"))
            rb = obj.rigid_body
            rb.type = params.get("body_type", "ACTIVE")
            rb.mass = max(0.001, float(params.get("mass", 1.0)))
            rb.friction = BU.clamp(params.get("friction", 0.5), 0, 100)
            rb.restitution = BU.clamp(params.get("bounciness", 0.0), 0, 1)
            rb.collision_shape = params.get("collision_shape", "CONVEX_HULL")
            done.append(name)
        except (AttributeError, RuntimeError, TypeError) as exc:
            skipped.append(f"{name} ({exc})")
    return {"rigid_bodies": done, "skipped": skipped}


@register_tool("physics.add_cloth", "physics", "Add cloth",
               "Add a cloth simulation with a fabric preset.",
               params={
                   "object": {"type": "string", "required": True},
                   "preset": {"type": "string", "default": "COTTON",
                              "choices": list(CLOTH_PRESETS)},
                   "quality": {"type": "int", "default": 5},
                   "pin_group": {"type": "string", "default": ""},
               })
def physics_cloth(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    if obj.type != "MESH":
        raise ToolError("TOOL_FAILED", "Cloth needs a MESH object.")
    mod = obj.modifiers.new(name="AI_Cloth", type="CLOTH")
    settings = mod.settings
    preset_values = {
        "COTTON": {"mass": 0.3, "tension": 15, "compression": 15, "shear": 5},
        "DENIM": {"mass": 0.5, "tension": 40, "compression": 40, "shear": 15},
        "LEATHER": {"mass": 0.6, "tension": 80, "compression": 80, "shear": 30},
        "RUBBER": {"mass": 0.4, "tension": 25, "compression": 25, "shear": 25},
        "SILK": {"mass": 0.15, "tension": 5, "compression": 5, "shear": 2},
    }
    values = preset_values.get(params.get("preset", "COTTON"), preset_values["COTTON"])
    try:
        settings.mass = values["mass"]
        settings.tension_stiffness = values["tension"]
        settings.compression_stiffness = values["compression"]
        settings.shear_stiffness = values["shear"]
        settings.quality = max(1, min(int(params.get("quality", 5)), 20))
        if params.get("pin_group"):
            if params["pin_group"] not in obj.vertex_groups:
                raise ToolError("OBJECT_NOT_FOUND",
                                f"Vertex group '{params['pin_group']}' not on '{obj.name}'.")
            settings.vertex_group_mass = params["pin_group"]
    except ToolError:
        raise
    except (AttributeError, TypeError) as exc:
        raise ToolError("TOOL_FAILED", f"Cloth setup failed: {exc}")
    return {"object": obj.name, "modifier": mod.name,
            "preset": params.get("preset", "COTTON")}


@register_tool("physics.add_collision", "physics", "Add collision",
               "Make an object a collision obstacle for cloth/particles.",
               params={
                   "object": {"type": "string", "required": True},
                   "thickness_outer": {"type": "float", "default": 0.02},
                   "damping": {"type": "float", "default": 0.0},
               })
def physics_collision(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    mod = obj.modifiers.new(name="AI_Collision", type="COLLISION")
    try:
        mod.settings.thickness_outer = float(params.get("thickness_outer", 0.02))
        mod.settings.damping = BU.clamp(params.get("damping", 0.0), 0, 1)
    except (AttributeError, TypeError):
        pass
    return {"object": obj.name, "modifier": mod.name}


@register_tool("physics.add_force", "physics", "Add force field",
               "Create a wind/turbulence/vortex/magnet/drag force field.",
               params={
                   "kind": {"type": "string", "default": "WIND",
                            "choices": list(FORCE_KINDS)},
                   "name": {"type": "string", "default": "AI_Force"},
                   "location": {"type": "list", "default": [0, 0, 2]},
                   "strength": {"type": "float", "default": 10.0},
                   "size": {"type": "float", "default": None},
               })
def physics_force(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    obj = bpy.data.objects.new(str(params.get("name", "AI_Force")), None)
    obj.location = BU.to_vec3(params.get("location"), (0, 0, 2))
    try:
        obj.field.type = params.get("kind", "WIND")
        obj.field.strength = float(params.get("strength", 10.0))
        if params.get("size") is not None:
            obj.field.size = float(params["size"])
    except (AttributeError, TypeError) as exc:
        bpy.data.objects.remove(obj, do_unlink=True)
        raise ToolError("TOOL_FAILED", f"Force field failed: {exc}")
    BU.link_to_collection(obj, "Physics")
    return {"name": obj.name, "kind": obj.field.type}


@register_tool("physics.set_gravity", "physics", "Set gravity",
               "Enable/disable and set scene gravity.",
               params={
                   "use_gravity": {"type": "bool", "default": True},
                   "gravity": {"type": "list", "default": [0, 0, -9.81]},
               })
def physics_gravity(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    scene = BU.ctx_scene()
    scene.use_gravity = bool(params.get("use_gravity", True))
    scene.gravity = BU.to_vec3(params.get("gravity"), (0, 0, -9.81))
    return {"use_gravity": scene.use_gravity,
            "gravity": [scene.gravity[0], scene.gravity[1], scene.gravity[2]]}


@register_tool("physics.bake_to_keyframes", "physics", "Bake rigid to keyframes",
               "Bake the rigid-body simulation into object keyframes.",
               params={
                   "frame_start": {"type": "int", "default": None},
                   "frame_end": {"type": "int", "default": None},
               })
def physics_bake(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    scene = BU.ctx_scene()
    if scene.rigidbody_world is None:
        raise ToolError("TOOL_FAILED", "No rigid-body world in the scene.")
    start = params.get("frame_start", scene.frame_start)
    end = params.get("frame_end", scene.frame_end)
    bodies = [o for o in bpy.data.objects if getattr(o, "rigid_body", None)]
    if not bodies:
        raise ToolError("TOOL_FAILED", "No rigid-body objects to bake.")
    BU.set_mode("OBJECT")
    BU.select_only(bodies)
    BU.set_active(bodies[0], select=False)
    try:
        bpy.ops.rigidbody.bake_to_keyframes(frame_start=int(start),
                                            frame_end=int(end))
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Bake failed: {exc}")
    return {"baked": [o.name for o in bodies], "frames": [int(start), int(end)]}


@register_tool("physics.summary", "physics", "Physics summary",
               "List rigid bodies, cloth/collision modifiers and force fields.",
               params={})
def physics_summary(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    bodies, cloths, collisions, forces = [], [], [], []
    for obj in bpy.data.objects:
        if getattr(obj, "rigid_body", None) is not None:
            bodies.append(obj.name)
        for mod in getattr(obj, "modifiers", []):
            if mod.type == "CLOTH":
                cloths.append(obj.name)
            elif mod.type == "COLLISION":
                collisions.append(obj.name)
        try:
            if obj.type == "EMPTY" and getattr(obj.field, "type", "NONE") != "NONE":
                forces.append({"name": obj.name, "kind": obj.field.type})
        except (AttributeError, RuntimeError):
            pass
    return {"rigid_bodies": bodies, "cloth": cloths,
            "collisions": collisions, "forces": forces}
