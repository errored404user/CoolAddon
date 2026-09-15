"""Safe, reusable wrappers around bpy used by every tool module."""

from __future__ import annotations

import math
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from ..tools.base import ToolError, require_bpy


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------

def ctx_scene():
    bpy = require_bpy()
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        raise ToolError("TOOL_FAILED", "No active scene.")
    return scene


def deselect_all() -> None:
    bpy = require_bpy()
    try:
        bpy.ops.object.select_all(action="DESELECT")
    except RuntimeError:
        for obj in bpy.context.selected_objects:
            obj.select_set(False)


def select_only(objs) -> None:
    bpy = require_bpy()
    deselect_all()
    for obj in objs:
        try:
            obj.select_set(True)
        except (AttributeError, RuntimeError):
            continue


def set_active(obj, select: bool = True) -> None:
    bpy = require_bpy()
    try:
        if select:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    except (AttributeError, RuntimeError) as exc:
        raise ToolError("TOOL_FAILED", f"Could not activate object: {exc}")


def set_mode(mode: str = "OBJECT") -> None:
    bpy = require_bpy()
    try:
        if bpy.context.mode != f"OBJECT" and mode == "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        elif bpy.context.mode != f"EDIT_MESH" and mode == "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")
        elif mode not in ("OBJECT", "EDIT"):
            bpy.ops.object.mode_set(mode=mode)
    except RuntimeError:
        pass  # e.g. no active object — non-fatal for most tools


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def find_object(name: str):
    bpy = require_bpy()
    if not name:
        return None
    return bpy.data.objects.get(name)


def find_object_fuzzy(name: str):
    """Case-insensitive exact, then substring match. Returns obj or None."""
    bpy = require_bpy()
    if not name:
        return None
    if name in bpy.data.objects:
        return bpy.data.objects[name]
    lowered = name.lower()
    for obj in bpy.data.objects:
        if obj.name.lower() == lowered:
            return obj
    for obj in bpy.data.objects:
        if lowered in obj.name.lower():
            return obj
    return None


def require_object(name: str, *, fuzzy: bool = True):
    obj = find_object_fuzzy(name) if fuzzy else find_object(name)
    if obj is None:
        bpy = require_bpy()
        available = sorted(o.name for o in bpy.data.objects)[:12]
        raise ToolError(
            "OBJECT_NOT_FOUND",
            f"Object '{name}' not found.",
            {"available": available},
        )
    return obj


def require_collection(name: str):
    bpy = require_bpy()
    coll = bpy.data.collections.get(name)
    if coll is None:
        raise ToolError("OBJECT_NOT_FOUND", f"Collection '{name}' not found.")
    return coll


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

def ensure_collection(name: str, parent_name: Optional[str] = None):
    bpy = require_bpy()
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        if parent_name and parent_name in bpy.data.collections:
            bpy.data.collections[parent_name].children.link(coll)
        else:
            ctx_scene().collection.children.link(coll)
    return coll


def link_to_collection(obj, collection_name: Optional[str] = None):
    bpy = require_bpy()
    if collection_name:
        coll = ensure_collection(collection_name)
    else:
        coll = ctx_scene().collection
    try:
        coll.objects.link(obj)
    except RuntimeError:
        pass  # already linked
    return coll


def unlink_everywhere(obj) -> None:
    for coll in list(obj.users_collection):
        try:
            coll.objects.unlink(obj)
        except RuntimeError:
            pass


def safe_remove_object(obj) -> None:
    bpy = require_bpy()
    try:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        # Best-effort orphan cleanup for meshes/curves (never for shared libs).
        if data is not None and getattr(data, "users", 1) == 0:
            try:
                if hasattr(bpy.data.meshes, "remove") and data in bpy.data.meshes[:]:
                    bpy.data.meshes.remove(data)
            except (AttributeError, RuntimeError, TypeError):
                pass
    except (AttributeError, RuntimeError) as exc:
        raise ToolError("TOOL_FAILED", f"Could not remove object: {exc}")


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

def to_vec3(value: Any, default: Sequence[float] = (0.0, 0.0, 0.0)) -> Tuple[float, float, float]:
    if value is None:
        value = default
    if isinstance(value, (int, float)):
        return (float(value), float(value), float(value))
    try:
        items = list(value)
    except TypeError:
        raise ToolError("INVALID_PARAMS", f"Expected a 3-item vector, got {value!r}.")
    if len(items) == 1:
        items = items * 3
    if len(items) != 3:
        raise ToolError("INVALID_PARAMS", f"Expected a 3-item vector, got {value!r}.")
    try:
        return (float(items[0]), float(items[1]), float(items[2]))
    except (TypeError, ValueError):
        raise ToolError("INVALID_PARAMS", f"Invalid vector values: {value!r}.")


def to_rgba(value: Any, default: Sequence[float] = (0.8, 0.8, 0.8, 1.0)):
    if value is None:
        value = default
    items = list(value) if isinstance(value, (list, tuple)) else [value]
    if len(items) == 3:
        items = items + [1.0]
    if len(items) != 4:
        raise ToolError("INVALID_PARAMS", f"Expected RGB/RGBA color, got {value!r}.")
    try:
        return tuple(max(0.0, min(1.0, float(c))) for c in items)
    except (TypeError, ValueError):
        raise ToolError("INVALID_PARAMS", f"Invalid color values: {value!r}.")


def deg_to_rad(value: Any) -> Tuple[float, float, float]:
    x, y, z = to_vec3(value, (0.0, 0.0, 0.0))
    return (math.radians(x), math.radians(y), math.radians(z))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def ensure_material(name: str, use_nodes: bool = True):
    bpy = require_bpy()
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)
    mat.use_nodes = use_nodes
    return mat


def principled_bsdf(mat):
    """Return the Principled BSDF node, creating a minimal node setup if needed."""
    if not mat.use_nodes:
        mat.use_nodes = True
    nodes = mat.node_tree.nodes
    for node in nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    mat.node_tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return bsdf


def assign_material(obj, mat) -> None:
    try:
        if obj.type in ("MESH", "CURVE", "SURFACE", "META", "FONT", "VOLUME", "GPENCIL"):
            if len(obj.data.materials) == 0:
                obj.data.materials.append(mat)
            else:
                obj.data.materials[0] = mat
        else:
            raise ToolError("TOOL_FAILED", f"Object type '{obj.type}' cannot hold materials.")
    except ToolError:
        raise
    except (AttributeError, RuntimeError) as exc:
        raise ToolError("TOOL_FAILED", f"Could not assign material: {exc}")


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def object_summary(obj) -> Dict[str, Any]:
    try:
        return {
            "name": obj.name,
            "type": obj.type,
            "location": [round(float(v), 4) for v in obj.location],
            "selected": bool(obj.select_get()),
            "visible": bool(obj.visible_get()),
            "materials": [m.name if m else None for m in getattr(obj.data, "materials", [])]
            if hasattr(obj, "data") and obj.data else [],
            "modifiers": [m.name for m in getattr(obj, "modifiers", [])],
        }
    except (AttributeError, RuntimeError):
        return {"name": getattr(obj, "name", "?"), "type": "UNKNOWN"}


def purge_orphans() -> Dict[str, int]:
    """Purge orphan data-blocks. Returns counts per data type (best effort)."""
    bpy = require_bpy()
    counts: Dict[str, int] = {}
    for attr in ("meshes", "materials", "images", "curves", "actions", "textures", "node_groups"):
        store = getattr(bpy.data, attr, None)
        if store is None or not hasattr(store, "remove"):
            continue
        removed = 0
        for block in list(store):
            try:
                if getattr(block, "users", 1) == 0 and not getattr(block, "use_fake_user", False):
                    store.remove(block)
                    removed += 1
            except (AttributeError, RuntimeError, TypeError):
                continue
        counts[attr] = removed
    return counts


def match_names(pattern: str, names: Iterable[str]) -> List[str]:
    """Simple wildcard (* suffix/prefix/contains) + exact matcher."""
    import fnmatch

    pattern = (pattern or "").strip()
    names = list(names)
    if not pattern or pattern == "*":
        return names
    lowered = {n.lower(): n for n in names}
    if pattern.lower() in lowered:
        return [lowered[pattern.lower()]]
    matched = fnmatch.filter(names, pattern)
    if matched:
        return matched
    # Fallback: case-insensitive substring.
    return [n for n in names if pattern.lower() in n.lower()]
