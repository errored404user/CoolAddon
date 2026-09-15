"""Error recovery: map tool failures to safe automatic corrections.

Recovery is deliberately conservative: only deterministic, non-destructive
fixes (name fuzzy-matching, degenerate-aim nudges) are attempted. Anything
else is reported back so the user — not a guessing loop — decides.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

TARGET_KEYS = ("object", "target", "mesh", "armature", "camera", "material",
               "base_object", "scatter_object", "tree", "collection",
               "look_at_object", "pole_target", "parent")


def _scene_names(context: Optional[Dict[str, Any]]) -> List[str]:
    if not context:
        return []
    names = []
    for entry in context.get("objects") or []:
        if isinstance(entry, dict) and entry.get("name"):
            names.append(entry["name"])
    names += [m for m in context.get("materials", []) if isinstance(m, str)]
    names += [c for c in context.get("collections", []) if isinstance(c, str)]
    return names


def suggest_fix(tool_id: str, params: Dict[str, Any], error: Dict[str, Any],
                context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Return {'params': fixed, 'note': str} or None when unrecoverable."""
    code = (error or {}).get("code", "")
    message = (error or {}).get("message", "") or ""
    details = (error or {}).get("details") or {}

    # 1) Unknown names -> closest real scene name.
    if code == "OBJECT_NOT_FOUND":
        available = list(details.get("available") or []) + _scene_names(context)
        available = [a for a in available if isinstance(a, str)]
        if not available:
            return None
        for key in TARGET_KEYS:
            value = params.get(key)
            if isinstance(value, str) and value and value not in available:
                match = difflib.get_close_matches(value, available, n=1, cutoff=0.55)
                if match and match[0] != value:
                    fixed = dict(params)
                    fixed[key] = match[0]
                    return {"params": fixed,
                            "note": f"object '{value}' not found — using '{match[0]}'"}
        # Lists of names (objects/meshes/names): substitute what we can.
        for key in ("objects", "meshes", "names"):
            values = params.get(key)
            if isinstance(values, list) and values:
                fixed_list, changed = [], False
                for value in values:
                    if isinstance(value, str) and value not in available:
                        match = difflib.get_close_matches(value, available, n=1, cutoff=0.55)
                        if match:
                            fixed_list.append(match[0])
                            changed = True
                            continue
                    fixed_list.append(value)
                if changed:
                    fixed = dict(params)
                    fixed[key] = fixed_list
                    return {"params": fixed,
                            "note": f"fuzzy-matched missing names in '{key}'"}
        return None

    # 2) Camera aiming exactly at its own position -> nudge the aim point.
    if "coincide" in message and tool_id in ("camera.create", "camera.look_at",
                                             "cutscene.create_shot"):
        fixed = dict(params)
        if isinstance(fixed.get("look_at"), (list, tuple)) and len(fixed["look_at"]) == 3:
            point = list(fixed["look_at"])
            point[2] = float(point[2]) + 0.5
            fixed["look_at"] = point
            return {"params": fixed, "note": "nudged degenerate look-at target"}
        if isinstance(fixed.get("target_point"), (list, tuple)) and len(fixed["target_point"]) == 3:
            point = list(fixed["target_point"])
            point[2] = float(point[2]) + 0.5
            fixed["target_point"] = point
            return {"params": fixed, "note": "nudged degenerate look-at target"}
        return None

    # 3) Selection-based tools with an empty selection -> fall back to active object.
    if code in ("INVALID_PARAMS", "TOOL_FAILED") and "selection" in message.lower():
        if params.get("use_selection"):
            fixed = dict(params)
            fixed.pop("use_selection", None)
            fixed["objects"] = ["$active_object"]
            return {"params": fixed,
                    "note": "selection was empty — falling back to active object"}

    return None
