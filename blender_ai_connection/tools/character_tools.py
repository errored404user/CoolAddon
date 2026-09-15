"""Character tools: armatures, IK, skinning, poses, humanoid builder."""

from __future__ import annotations

from typing import Any, Dict, List

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU


def _to_edit_mode(rig) -> None:
    import bpy
    BU.set_mode("OBJECT")
    BU.set_active(rig)
    try:
        bpy.ops.object.mode_set(mode="EDIT")
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Could not enter edit mode: {exc}")


@register_tool("character.create_armature", "character", "Create armature",
               "Build an armature from a bone spec list.",
               params={
                   "name": {"type": "string", "default": "AI_Rig"},
                   "bones": {"type": "list", "required": True,
                             "description": "[{name, head:[x,y,z], tail:[x,y,z], parent?}]"},
                   "location": {"type": "list", "default": [0, 0, 0]},
                   "collection": {"type": "string", "default": "Characters"},
               })
def create_armature(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    bones = params.get("bones") or []
    if not bones:
        raise ToolError("INVALID_PARAMS", "bones must be a non-empty list.")
    amt = bpy.data.armatures.new(str(params.get("name", "AI_Rig")))
    rig = bpy.data.objects.new(str(params.get("name", "AI_Rig")), amt)
    rig.location = BU.to_vec3(params.get("location"), (0, 0, 0))
    BU.link_to_collection(rig, params.get("collection") or "Characters")
    _to_edit_mode(rig)
    made: List[str] = []
    try:
        for spec in bones:
            if not isinstance(spec, dict) or "name" not in spec:
                raise ToolError("INVALID_PARAMS", "Each bone needs {name, head, tail}.")
            bone = amt.edit_bones.new(str(spec["name"]))
            bone.head = BU.to_vec3(spec.get("head"), (0, 0, 0))
            bone.tail = BU.to_vec3(spec.get("tail"), (0, 0, 1))
            if (bone.tail - bone.head).length < 1e-5:
                bone.tail = bone.head + __import__("mathutils").Vector((0, 0, 0.1))
            made.append(bone.name)
        for spec in bones:
            parent = spec.get("parent")
            if parent:
                child = amt.edit_bones.get(str(spec["name"]))
                par = amt.edit_bones.get(str(parent))
                if child is not None and par is not None:
                    child.parent = par
    finally:
        BU.set_mode("OBJECT")
    rig.show_in_front = True
    return {"armature": rig.name, "bones": made}


@register_tool("character.add_ik", "character", "Add IK",
               "Add an inverse-kinematics constraint to a bone.",
               params={
                   "armature": {"type": "string", "required": True},
                   "bone": {"type": "string", "required": True},
                   "target": {"type": "string", "default": "",
                              "description": "Existing target object (empty)"},
                   "create_target": {"type": "bool", "default": True},
                   "target_location": {"type": "list", "default": None},
                   "chain_count": {"type": "int", "default": 2},
                   "pole_target": {"type": "string", "default": ""},
               })
def add_ik(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    rig = BU.require_object(params["armature"])
    if rig.type != "ARMATURE":
        raise ToolError("TOOL_FAILED", f"'{rig.name}' is not an armature.")
    pbone = rig.pose.bones.get(params["bone"])
    if pbone is None:
        raise ToolError("OBJECT_NOT_FOUND",
                        f"Bone '{params['bone']}' not in '{rig.name}'.",
                        {"bones": [b.name for b in rig.pose.bones][:30]})
    target = None
    if params.get("target"):
        target = BU.require_object(params["target"])
    elif params.get("create_target", True):
        loc = params.get("target_location")
        if loc is None:
            # Default: slightly beyond the bone tail in world space.
            tail_world = rig.matrix_world @ pbone.tail
            head_world = rig.matrix_world @ pbone.head
            direction = tail_world - head_world
            loc = tail_world + direction * 0.5 if direction.length > 1e-6 else tail_world
        target = bpy.data.objects.new(f"IK_{pbone.name}_Target", None)
        target.location = BU.to_vec3(loc)
        target.empty_display_size = 0.2
        BU.link_to_collection(target, "Characters")
    if target is None:
        raise ToolError("INVALID_PARAMS", "Provide target or set create_target=true.")
    con = pbone.constraints.new(type="IK")
    con.target = target
    con.chain_count = max(0, min(int(params.get("chain_count", 2)), 10))
    if params.get("pole_target"):
        con.pole_target = BU.require_object(params["pole_target"])
    return {"armature": rig.name, "bone": pbone.name,
            "constraint": con.name, "target": target.name}


@register_tool("character.parent_with_weights", "character", "Skin mesh to rig",
               "Parent mesh(es) to an armature with automatic weights.",
               params={
                   "mesh": {"type": "string", "default": ""},
                   "meshes": {"type": "list", "default": []},
                   "armature": {"type": "string", "required": True},
                   "method": {"type": "string", "default": "ARMATURE_AUTO",
                              "choices": ["ARMATURE_AUTO", "ARMATURE_ENVELOPE", "OBJECT"]},
               })
def parent_weights(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    rig = BU.require_object(params["armature"])
    if rig.type != "ARMATURE":
        raise ToolError("TOOL_FAILED", f"'{rig.name}' is not an armature.")
    names = list(params.get("meshes") or [])
    if params.get("mesh"):
        names.append(params["mesh"])
    if not names:
        raise ToolError("INVALID_PARAMS", "Provide mesh or meshes.")
    meshes = [BU.require_object(n) for n in dict.fromkeys(names)]
    BU.set_mode("OBJECT")
    BU.select_only(meshes)
    BU.set_active(rig, select=False)
    rig.select_set(True)
    method = {"ARMATURE_AUTO": "ARMATURE_AUTO",
              "ARMATURE_ENVELOPE": "ARMATURE_ENVELOPE",
              "OBJECT": "OBJECT"}.get(params.get("method", "ARMATURE_AUTO"), "ARMATURE_AUTO")
    try:
        if method == "OBJECT":
            bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)
        else:
            bpy.ops.object.parent_set(type=method)
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Parenting failed: {exc}")
    return {"armature": rig.name, "skinned": [m.name for m in meshes], "method": method}


@register_tool("character.create_pose", "character", "Create pose",
               "Pose bones, optionally keyframed on the timeline.",
               params={
                   "armature": {"type": "string", "required": True},
                   "pose": {"type": "dict", "required": True,
                            "description": "{bone: {rotation_deg?, location?, scale?}}"},
                   "frame": {"type": "int", "default": None},
                   "keyframe": {"type": "bool", "default": False},
               })
def create_pose(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    rig = BU.require_object(params["armature"])
    if rig.type != "ARMATURE":
        raise ToolError("TOOL_FAILED", f"'{rig.name}' is not an armature.")
    pose = params.get("pose") or {}
    if not pose:
        raise ToolError("INVALID_PARAMS", "pose must be a non-empty dict.")
    BU.set_mode("OBJECT")
    BU.set_active(rig)
    try:
        bpy.ops.object.mode_set(mode="POSE")
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Could not enter pose mode: {exc}")
    posed, missing = [], []
    try:
        for bone_name, values in pose.items():
            pb = rig.pose.bones.get(bone_name)
            if pb is None or not isinstance(values, dict):
                missing.append(bone_name)
                continue
            try:
                pb.rotation_mode = "XYZ"
            except (AttributeError, TypeError):
                pass
            if values.get("rotation_deg") is not None:
                pb.rotation_euler = BU.deg_to_rad(values["rotation_deg"])
            if values.get("location") is not None:
                pb.location = BU.to_vec3(values["location"])
            if values.get("scale") is not None:
                pb.scale = BU.to_vec3(values["scale"], (1, 1, 1))
            if params.get("keyframe") and params.get("frame") is not None:
                frame = int(params["frame"])
                try:
                    if values.get("rotation_deg") is not None:
                        pb.keyframe_insert("rotation_euler", frame=frame)
                    if values.get("location") is not None:
                        pb.keyframe_insert("location", frame=frame)
                    if values.get("scale") is not None:
                        pb.keyframe_insert("scale", frame=frame)
                except (AttributeError, RuntimeError, TypeError):
                    pass
            posed.append(bone_name)
    finally:
        BU.set_mode("OBJECT")
    return {"armature": rig.name, "posed": posed, "missing_bones": missing}


@register_tool("character.add_constraint", "character", "Add bone/object constraint",
               "Add a constraint to an object or a pose bone.",
               params={
                   "object": {"type": "string", "default": ""},
                   "armature": {"type": "string", "default": ""},
                   "bone": {"type": "string", "default": ""},
                   "constraint": {"type": "string", "required": True,
                                  "description": "e.g. TRACK_TO, COPY_LOCATION, COPY_ROTATION, LIMIT_ROTATION, STRETCH_TO"},
                   "target": {"type": "string", "default": ""},
                   "settings": {"type": "dict", "default": {}},
               })
def add_constraint(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    holder = None
    label = ""
    if params.get("bone"):
        rig = BU.require_object(params.get("armature") or params.get("object") or "")
        if rig.type != "ARMATURE":
            raise ToolError("TOOL_FAILED", f"'{rig.name}' is not an armature.")
        holder = rig.pose.bones.get(params["bone"])
        if holder is None:
            raise ToolError("OBJECT_NOT_FOUND", f"Bone '{params['bone']}' missing.")
        label = f"{rig.name}:{holder.name}"
    else:
        holder = BU.require_object(params.get("object") or params.get("armature") or "")
        label = holder.name
    ctype = str(params.get("constraint", "")).upper()
    try:
        con = holder.constraints.new(type=ctype)
    except (AttributeError, RuntimeError, TypeError) as exc:
        raise ToolError("TOOL_FAILED", f"Cannot add constraint '{ctype}': {exc}")
    if params.get("target"):
        try:
            con.target = BU.require_object(params["target"])
        except (AttributeError, TypeError):
            pass
    for key, value in (params.get("settings") or {}).items():
        try:
            setattr(con, key, value)
        except (AttributeError, TypeError, ValueError):
            pass
    return {"holder": label, "constraint": con.name, "type": ctype}


@register_tool("character.build_simple_humanoid", "character", "Build humanoid",
               "Build a stylized rigged humanoid (meshes + armature + skinning).",
               params={
                   "name": {"type": "string", "default": "AI_Character"},
                   "height": {"type": "float", "default": 1.8},
                   "location": {"type": "list", "default": [0, 0, 0]},
                   "with_rig": {"type": "bool", "default": True},
                   "collection": {"type": "string", "default": "Characters"},
               })
def build_humanoid(params: Dict[str, Any]) -> Dict[str, Any]:
    from .material_tools import material_assign, material_create
    from .modeling_tools import create_primitive

    bpy = require_bpy()
    prefix = str(params.get("name", "AI_Character"))
    height = BU.clamp(params.get("height", 1.8), 0.5, 5.0)
    bx, by, bz = BU.to_vec3(params.get("location"), (0, 0, 0))
    coll = params.get("collection") or "Characters"

    def part(kind, name, loc, scale, size=1.0):
        return create_primitive({"kind": kind, "name": f"{prefix}_{name}",
                                 "location": [bx + loc[0], by + loc[1], bz + loc[2]],
                                 "scale": list(scale), "size": size,
                                 "collection": coll})["name"]

    u = height  # total height unit
    torso = part("CUBE", "Torso", (0, 0, u * 0.62), (0.16 * u, 0.1 * u, 0.17 * u), 2.0)
    head = part("SPHERE_UV", "Head", (0, 0, u * 0.9), (1, 1, 1), 0.11 * u * 2)
    pelvis = part("CUBE", "Pelvis", (0, 0, u * 0.48), (0.13 * u, 0.09 * u, 0.07 * u), 2.0)
    limbs = []
    for side, sx in (("L", 1), ("R", -1)):
        limbs.append(part("CYLINDER", f"UpperArm_{side}", (sx * 0.22 * u, 0, u * 0.68),
                           (1, 1, 1), 0.05 * u * 2))
        bpy.data.objects[limbs[-1]].rotation_euler[1] = sx * 0.15
        limbs.append(part("CYLINDER", f"Forearm_{side}", (sx * 0.25 * u, 0, u * 0.52),
                           (1, 1, 1), 0.045 * u * 2))
        limbs.append(part("CYLINDER", f"Thigh_{side}", (sx * 0.08 * u, 0, u * 0.35),
                           (1, 1, 1), 0.07 * u * 2))
        limbs.append(part("CYLINDER", f"Shin_{side}", (sx * 0.08 * u, 0, u * 0.15),
                           (1, 1, 1), 0.055 * u * 2))
    meshes = [torso, head, pelvis] + limbs

    # Materials: skin for head, outfit for body.
    material_create({"name": f"{prefix}_Skin", "preset": "skin"})
    material_create({"name": f"{prefix}_Outfit", "preset": "fabric",
                     "base_color": [0.15, 0.25, 0.55, 1.0]})
    material_assign({"material": f"{prefix}_Skin", "objects": [head]})
    material_assign({"material": f"{prefix}_Outfit",
                     "objects": [m for m in meshes if m != head]})

    rig_name = ""
    bones_made: List[str] = []
    if params.get("with_rig", True):
        hip_y = u * 0.48
        specs = [
            {"name": "Hips", "head": (0, 0, hip_y), "tail": (0, 0, hip_y + 0.08 * u)},
            {"name": "Spine", "head": (0, 0, hip_y), "tail": (0, 0, u * 0.72), "parent": "Hips"},
            {"name": "Head", "head": (0, 0, u * 0.78), "tail": (0, 0, u * 0.95), "parent": "Spine"},
        ]
        for side, sx in (("L", 1), ("R", -1)):
            specs += [
                {"name": f"UpperArm_{side}", "head": (sx * 0.2 * u, 0, u * 0.72),
                 "tail": (sx * 0.24 * u, 0, u * 0.58), "parent": "Spine"},
                {"name": f"Forearm_{side}", "head": (sx * 0.24 * u, 0, u * 0.58),
                 "tail": (sx * 0.26 * u, 0, u * 0.44), "parent": f"UpperArm_{side}"},
                {"name": f"Thigh_{side}", "head": (sx * 0.08 * u, 0, hip_y),
                 "tail": (sx * 0.08 * u, 0, u * 0.26), "parent": "Hips"},
                {"name": f"Shin_{side}", "head": (sx * 0.08 * u, 0, u * 0.26),
                 "tail": (sx * 0.08 * u, 0, u * 0.03), "parent": f"Thigh_{side}"},
            ]
        # Offset bones by base location.
        for spec in specs:
            spec["head"] = (spec["head"][0] + bx, spec["head"][1] + by, spec["head"][2] + bz)
            spec["tail"] = (spec["tail"][0] + bx, spec["tail"][1] + by, spec["tail"][2] + bz)
        rig = create_armature({"name": f"{prefix}_Rig", "bones": specs,
                               "collection": coll})
        rig_name = rig["armature"]
        bones_made = rig["bones"]
        parent_weights({"meshes": meshes, "armature": rig_name})
    return {"character": prefix, "meshes": meshes, "armature": rig_name,
            "bones": bones_made, "height": height}
