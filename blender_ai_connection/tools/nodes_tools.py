"""Geometry Nodes + node-tree tools: create, inspect, wire."""

from __future__ import annotations

from typing import Any, Dict

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

GEONODES_PRESETS = ("smooth_subdiv", "displace_noise", "scatter")


def _get_group(name: str):
    bpy = require_bpy()
    tree = bpy.data.node_groups.get(name)
    if tree is None:
        raise ToolError("OBJECT_NOT_FOUND", f"Node group '{name}' not found.",
                        {"available": sorted(g.name for g in bpy.data.node_groups)[:20]})
    return tree


def _new_group(name: str):
    bpy = require_bpy()
    tree = bpy.data.node_groups.new(name=name, type="GeometryNodeTree")
    # Interface socket (Blender 4.x API with 3.x fallback).
    try:
        if hasattr(tree, "interface") and hasattr(tree.interface, "new_socket"):
            tree.interface.new_socket(name="Geometry", in_out="INPUT",
                                      socket_type="NodeSocketGeometry")
            tree.interface.new_socket(name="Geometry", in_out="OUTPUT",
                                      socket_type="NodeSocketGeometry")
        else:  # Blender 3.x
            tree.inputs.new("NodeSocketGeometry", "Geometry")
            tree.outputs.new("NodeSocketGeometry", "Geometry")
    except (AttributeError, RuntimeError, TypeError):
        pass
    return tree


def _add_node(tree, node_type: str, name: str = "", x: float = 0, y: float = 0):
    try:
        node = tree.nodes.new(type=node_type)
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Cannot add node '{node_type}': {exc}")
    if name:
        node.name = name
    node.location = (x, y)
    return node


def _set_node_settings(node, settings: Dict[str, Any]):
    applied, skipped = {}, []
    for key, value in (settings or {}).items():
        try:
            current = getattr(node, key)
            if isinstance(current, bool):
                value = bool(value)
            elif isinstance(current, int) and not isinstance(current, bool):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
            setattr(node, key, value)
            applied[key] = value
        except (AttributeError, TypeError, ValueError):
            skipped.append(key)
    return applied, skipped


def _set_socket(node, socket_name: str, value) -> bool:
    sock = node.inputs.get(socket_name)
    if sock is None or not hasattr(sock, "default_value"):
        return False
    try:
        default = sock.default_value
        if hasattr(default, "__len__") and isinstance(value, (list, tuple)):
            sock.default_value = tuple(value)
        elif isinstance(default, bool):
            sock.default_value = bool(value)
        elif isinstance(default, int) and not isinstance(default, bool):
            sock.default_value = int(value)
        elif isinstance(default, float):
            sock.default_value = float(value)
        else:
            sock.default_value = value
        return True
    except (AttributeError, TypeError, ValueError):
        return False


def _build_preset(tree, preset: str, p: Dict[str, Any]):
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    group_in = _add_node(tree, "NodeGroupInput", "Group Input", -400, 0)
    group_out = _add_node(tree, "NodeGroupOutput", "Group Output", 400, 0)

    if preset == "smooth_subdiv":
        levels = max(0, min(int(p.get("levels", 2)), 6))
        subdiv = _add_node(tree, "GeometryNodeSubdivisionSurface", "Subdivide", -150, 0)
        _set_socket(subdiv, "Level", levels)
        smooth = _add_node(tree, "GeometryNodeSetShadeSmooth", "Shade Smooth", 150, 0)
        links.new(group_in.outputs["Geometry"], subdiv.inputs["Mesh"])
        links.new(subdiv.outputs["Mesh"], smooth.inputs["Geometry"])
        links.new(smooth.outputs["Geometry"], group_out.inputs["Geometry"])

    elif preset == "displace_noise":
        scale = float(p.get("noise_scale", 2.0))
        strength = float(p.get("strength", 0.5))
        pos = _add_node(tree, "GeometryNodeInputPosition", "Position", -350, -250)
        noise = _add_node(tree, "ShaderNodeTexNoise", "Noise", -150, -250)
        _set_socket(noise, "Scale", scale)
        setpos = _add_node(tree, "GeometryNodeSetPosition", "Displace", 100, 0)
        links.new(pos.outputs["Position"], noise.inputs["Vector"])
        links.new(group_in.outputs["Geometry"], setpos.inputs["Geometry"])
        # Noise color (vector) drives offset; strength scales via math multiply.
        math = _add_node(tree, "ShaderNodeVectorMath", "Strength", -150, 50)
        math.operation = "SCALE"
        _set_socket(math, "Scale", strength)
        links.new(noise.outputs["Color"], math.inputs["Vector"])
        links.new(math.outputs["Vector"], setpos.inputs["Offset"])
        links.new(setpos.outputs["Geometry"], group_out.inputs["Geometry"])

    elif preset == "scatter":
        scatter_name = p.get("scatter_object") or ""
        if not scatter_name:
            raise ToolError("INVALID_PARAMS",
                            "scatter preset needs 'scatter_object' (name of object to instance).")
        scatter_obj = BU.require_object(scatter_name)
        count = max(1, min(int(p.get("count", 100)), 100000))
        obj_info = _add_node(tree, "GeometryNodeObjectInfo", "Object Info", -350, -250)
        obj_info.inputs["Object"].default_value = None
        try:
            # Object socket: assign via default_value on 4.x, else inputs[0].
            sock = obj_info.inputs.get("Object")
            if sock is not None:
                sock.default_value = scatter_obj
        except (AttributeError, TypeError):
            pass
        distribute = _add_node(tree, "GeometryNodeDistributePointsOnFaces",
                               "Distribute", -150, 0)
        try:
            distribute.distribute_method = "RANDOM"
        except (AttributeError, TypeError):
            pass
        _set_socket(distribute, "Density Max", float(count))
        _set_socket(distribute, "Density", float(count))
        instance = _add_node(tree, "GeometryNodeInstanceOnPoints", "Instance", 150, 0)
        _set_socket(instance, "Scale", BU.to_vec3(p.get("instance_scale"), (1, 1, 1)))
        links.new(group_in.outputs["Geometry"], distribute.inputs["Mesh"])
        links.new(distribute.outputs["Points"], instance.inputs["Points"])
        links.new(obj_info.outputs["Geometry"], instance.inputs["Instance"])
        links.new(instance.outputs["Instances"], group_out.inputs["Geometry"])
    return [n.name for n in tree.nodes]


@register_tool("nodes.create_geonodes", "nodes", "Create Geometry Nodes",
               "Create a Geometry Nodes group (preset) and attach it to an object.",
               params={
                   "object": {"type": "string", "required": True},
                   "name": {"type": "string", "default": "AI_GeoNodes"},
                   "preset": {"type": "string", "default": "smooth_subdiv",
                              "choices": list(GEONODES_PRESETS)},
                   "levels": {"type": "int", "default": 2},
                   "noise_scale": {"type": "float", "default": 2.0},
                   "strength": {"type": "float", "default": 0.5},
                   "scatter_object": {"type": "string", "default": ""},
                   "count": {"type": "int", "default": 100},
                   "instance_scale": {"type": "list", "default": [1, 1, 1]},
               })
def nodes_create(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    tree = _new_group(str(params.get("name", "AI_GeoNodes")))
    node_names = _build_preset(tree, params.get("preset", "smooth_subdiv"), params)
    mod = obj.modifiers.new(name=f"AI_Nodes_{tree.name}", type="NODES")
    mod.node_group = tree
    return {"object": obj.name, "tree": tree.name, "modifier": mod.name,
            "nodes": node_names}


@register_tool("nodes.add_node", "nodes", "Add node",
               "Add a node to a node group with optional settings.",
               params={
                   "tree": {"type": "string", "required": True},
                   "node_type": {"type": "string", "required": True,
                                 "description": "bl_idname, e.g. GeometryNodeJoin"},
                   "name": {"type": "string", "default": ""},
                   "location": {"type": "list", "default": [0, 0]},
                   "settings": {"type": "dict", "default": {}},
               })
def nodes_add(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    tree = _get_group(params["tree"])
    loc = params.get("location") or [0, 0]
    node = _add_node(tree, params["node_type"], params.get("name", ""),
                     float(loc[0]) if len(loc) > 0 else 0,
                     float(loc[1]) if len(loc) > 1 else 0)
    applied, skipped = _set_node_settings(node, params.get("settings") or {})
    return {"tree": tree.name, "node": node.name, "type": node.type,
            "applied": applied, "skipped": skipped}


@register_tool("nodes.link_nodes", "nodes", "Link nodes",
               "Create a link between two node sockets.",
               params={
                   "tree": {"type": "string", "required": True},
                   "from_node": {"type": "string", "required": True},
                   "from_socket": {"type": "string", "required": True},
                   "to_node": {"type": "string", "required": True},
                   "to_socket": {"type": "string", "required": True},
               })
def nodes_link(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    tree = _get_group(params["tree"])
    src = tree.nodes.get(params["from_node"])
    dst = tree.nodes.get(params["to_node"])
    if src is None:
        raise ToolError("OBJECT_NOT_FOUND", f"Node '{params['from_node']}' not in tree.")
    if dst is None:
        raise ToolError("OBJECT_NOT_FOUND", f"Node '{params['to_node']}' not in tree.")
    out_sock = src.outputs.get(params["from_socket"])
    in_sock = dst.inputs.get(params["to_socket"])
    if out_sock is None:
        raise ToolError("INVALID_PARAMS",
                        f"'{src.name}' has no output '{params['from_socket']}'.",
                        {"outputs": [o.name for o in src.outputs]})
    if in_sock is None:
        raise ToolError("INVALID_PARAMS",
                        f"'{dst.name}' has no input '{params['to_socket']}'.",
                        {"inputs": [i.name for i in dst.inputs]})
    try:
        tree.links.new(out_sock, in_sock)
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Link failed (type mismatch?): {exc}")
    return {"tree": tree.name, "linked": True}


@register_tool("nodes.inspect_tree", "nodes", "Inspect node tree",
               "Dump nodes and links of a node group or material tree.",
               params={
                   "tree": {"type": "string", "default": "",
                            "description": "Node group name"},
                   "material": {"type": "string", "default": "",
                                "description": "Material name (alternative)"},
               })
def nodes_inspect(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    tree = None
    label = ""
    if params.get("tree"):
        tree = _get_group(params["tree"])
        label = f"group:{tree.name}"
    elif params.get("material"):
        mat = bpy.data.materials.get(params["material"])
        if mat is None or not mat.use_nodes:
            raise ToolError("OBJECT_NOT_FOUND",
                            f"Material '{params['material']}' has no node tree.")
        tree = mat.node_tree
        label = f"material:{mat.name}"
    else:
        raise ToolError("INVALID_PARAMS", "Provide tree or material.")
    nodes = [{"name": n.name, "type": n.type, "bl_idname": n.bl_idname,
              "inputs": [i.name for i in n.inputs],
              "outputs": [o.name for o in n.outputs]} for n in tree.nodes]
    links = [{"from_node": l.from_node.name, "from_socket": l.from_socket.name,
              "to_node": l.to_node.name, "to_socket": l.to_socket.name}
             for l in tree.links]
    return {"tree": label, "nodes": nodes, "links": links,
            "counts": {"nodes": len(nodes), "links": len(links)}}


@register_tool("nodes.list_trees", "nodes", "List node trees",
               "List geometry node groups and their sizes.",
               params={})
def nodes_list(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    groups = []
    for tree in bpy.data.node_groups:
        try:
            groups.append({"name": tree.name, "type": tree.type,
                           "nodes": len(tree.nodes), "links": len(tree.links),
                           "users": tree.users})
        except (AttributeError, RuntimeError):
            continue
    return {"node_groups": groups}


@register_tool("nodes.apply_to_object", "nodes", "Attach nodes to object",
               "Add a Geometry Nodes modifier referencing an existing group.",
               params={
                   "object": {"type": "string", "required": True},
                   "tree": {"type": "string", "required": True},
               })
def nodes_apply(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    obj = BU.require_object(params["object"])
    tree = _get_group(params["tree"])
    mod = obj.modifiers.new(name=f"AI_Nodes_{tree.name}", type="NODES")
    mod.node_group = tree
    return {"object": obj.name, "tree": tree.name, "modifier": mod.name}
