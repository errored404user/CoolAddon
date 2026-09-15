"""AI mode registry: specialist definitions, routing keywords, LLM guidance.

Pure Python (no bpy). Adding a new mode = add one entry to MODE_DEFS plus a
``plan_<name>`` builder in :mod:`agent.planner` — nothing else must change.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


MODE_DEFS: Dict[str, Dict[str, Any]] = {
    "SMART": {
        "label": "Smart Agent",
        "description": "Auto-detects which specialist modes the task needs and "
                       "runs them in dependency order (model → materials → rig → "
                       "environment → animation → lighting → camera → verify).",
        "keywords": (),
        "tools": ("scene.inspect", "debug.diagnose"),
        "order": 0,
        "system_prompt": (
            "You are the Smart Agent router. Analyze the request, inspect the "
            "scene first (scene.inspect), then run only the domains the task "
            "needs, in dependency order: modeling → materials → character/rig → "
            "environment/procedural → physics → animation → lighting → "
            "camera/cutscene → render → verify (debug.diagnose). Reuse existing "
            "objects instead of recreating them. Never animate before the "
            "required objects exist. Verify important operations afterwards."
        ),
    },
    "MODELING": {
        "label": "Modeling",
        "description": "Professional 3D modeling: primitives, modifiers, booleans, clean topology.",
        "keywords": ("model", "mesh", "robot", "mech", "vehicle", "car", "truck",
                     "tank", "sword", "weapon", "gun", "chair", "table", "furniture",
                     "prop", "creature", "monster", "bevel", "boolean", "extrude",
                     "subdiv", "hard-surface", "low-poly", "topology", "sculpt-base"),
        "tools": ("modeling.create_primitive", "modeling.transform", "modeling.duplicate",
                  "modeling.join", "modeling.boolean", "modeling.add_modifier",
                  "modeling.apply_modifier", "modeling.bevel", "modeling.subdivide",
                  "modeling.symmetry", "modeling.set_shade", "modeling.extrude",
                  "modeling.decimate", "modeling.merge_by_distance"),
        "order": 10,
        "system_prompt": (
            "Modeling specialist. Prefer procedural modifiers (bevel, subsurf, "
            "mirror) over destructive edits. Keep scenes organized (collections, "
            "clear names), use clean topology, shade smooth where appropriate, "
            "and merge doubles at the end."
        ),
    },
    "MATERIAL": {
        "label": "Material",
        "description": "PBR shaders and textures: metal, glass, wood, skin, emissive, stylized.",
        "keywords": ("material", "texture", "shader", "metal", "plastic", "glass",
                     "wood", "stone", "marble", "fabric", "cloth", "skin", "ceramic",
                     "emissive", "glow", "neon", "chrome", "gold", "copper", "rust",
                     "principled", "roughness", "pbr", "node shader"),
        "tools": ("material.list", "material.create", "material.assign",
                  "material.set_principled", "material.create_node_setup",
                  "material.remove"),
        "order": 20,
        "system_prompt": (
            "Material specialist. Build node-based PBR materials (Principled "
            "BSDF + procedural bump/detail where useful). Reuse existing "
            "materials when they fit; never leave objects with empty slots "
            "when the task asks for finished shading."
        ),
    },
    "CHARACTER": {
        "label": "Character",
        "description": "Characters, armatures, IK, skinning, poses.",
        "keywords": ("character", "human", "humanoid", "person", "mannequin",
                     "rig", "rigging", "armature", "bone", "skinning", "weights",
                     "weight paint", "ik", "inverse kinematic", "pose", "posing"),
        "tools": ("character.create_armature", "character.add_ik",
                  "character.parent_with_weights", "character.create_pose",
                  "character.add_constraint", "character.build_simple_humanoid"),
        "order": 30,
        "system_prompt": (
            "Character specialist. Recognize when a task needs a rig vs a "
            "static mesh. Build clean bone chains, parent with automatic "
            "weights, verify deformation, and use IK for limbs when motion is "
            "required."
        ),
    },
    "ANIMATION": {
        "label": "Animation",
        "description": "Keyframes, motion, loops, timing, camera/object animation.",
        "keywords": ("animat", "keyframe", "motion", "walk", "run", "jump",
                     "loop", "turntable", "timeline", "interpolat", "f-curve",
                     "fcurve", "rotate object", "spin", "bounce", "fps"),
        "tools": ("animation.set_timeline", "animation.set_keyframe",
                  "animation.animate_transform", "animation.set_interpolation",
                  "animation.create_loop", "animation.clear_keyframes",
                  "animation.list_actions"),
        "order": 60,
        "system_prompt": (
            "Animation specialist. Set the timeline first, key transforms with "
            "sensible interpolation (LINEAR for constant motion, BEZIER for "
            "eased), build seamless loops with CYCLES modifiers, and keep "
            "frame ranges consistent across objects and cameras."
        ),
    },
    "ENVIRONMENT": {
        "label": "Environment",
        "description": "Complete environments: cities, forests, interiors, ruins, labs.",
        "keywords": ("environment", "city", "town", "castle", "fortress", "forest",
                     "jungle", "woods", "desert", "dune", "interior", "room",
                     "ruins", "temple", "village", "hut", "lab", "laboratory",
                     "station", "battlefield", "battle", "landscape", "terrain",
                     "world", "scene backdrop", "space station"),
        "tools": ("environment.create_terrain", "environment.scatter_objects",
                  "environment.create_preset", "environment.set_atmosphere",
                  "camera.create", "lighting.setup_preset"),
        "order": 40,
        "system_prompt": (
            "Environment specialist. Compose complete, art-directed spaces: "
            "ground/terrain, structures, props, atmosphere and a framing "
            "camera. Prefer linked duplicates and presets over thousands of "
            "unique objects."
        ),
    },
    "PROCEDURAL": {
        "label": "Procedural",
        "description": "Procedural generation + Geometry Nodes systems.",
        "keywords": ("procedural", "geometry node", "geonode", "geo-node",
                     "scatter", "building", "house", "tower", "skyscraper",
                     "stairs", "staircase", "array", "parametric", "modular",
                     "generator", "instances"),
        "tools": ("nodes.create_geonodes", "nodes.add_node", "nodes.link_nodes",
                  "nodes.inspect_tree", "nodes.list_trees", "nodes.apply_to_object",
                  "procedural.create_building", "procedural.create_stairs",
                  "procedural.array_distribute"),
        "order": 45,
        "system_prompt": (
            "Procedural specialist. Prefer parametric systems (Geometry Nodes, "
            "arrays, instancing) over manual repetition. Build node networks "
            "step by step, verify links with nodes.inspect_tree, and keep "
            "large scenes instanced so they stay editable."
        ),
    },
    "LIGHTING": {
        "label": "Lighting",
        "description": "Cinematic and professional lighting, world, HDRI.",
        "keywords": ("light", "lighting", "hdri", "sun", "lamp", "shadow",
                     "rim light", "three-point", "three point", "studio light",
                     "dramatic", "horror light", "volumetric", "atmosphere",
                     "world light", "exposure"),
        "tools": ("lighting.create", "lighting.setup_preset", "lighting.set_world",
                  "lighting.list", "environment.set_atmosphere"),
        "order": 70,
        "system_prompt": (
            "Lighting specialist. Motivate every light (key/fill/rim), match "
            "the requested mood (three-point, dramatic, horror, sci-fi, "
            "studio, product), and balance world/HDRI contribution so subjects "
            "read clearly."
        ),
    },
    "CUTSCENE": {
        "label": "Cutscene",
        "description": "Cinematic storytelling: shots, movement, markers, sequences.",
        "keywords": ("cutscene", "cinematic", "camera", "shot", "film", "trailer",
                     "sequence", "tracking shot", "dolly", "pan shot", "close-up",
                     "closeup", "wide shot", "orbit shot", "flythrough",
                     "fly-through", "camera move"),
        "tools": ("camera.create", "camera.look_at", "camera.track_to",
                  "camera.set_active", "camera.create_sequence", "camera.list",
                  "cutscene.create_shot", "cutscene.build_sequence",
                  "cutscene.add_camera_shake", "cutscene.list_shots"),
        "order": 80,
        "system_prompt": (
            "Cutscene specialist. Tell the story in shots: establish (wide), "
            "develop (movement/orbit), emphasize (close-up). Bind cameras to "
            "timeline markers, keep movement motivated, add shake sparingly, "
            "and ensure the timeline covers every shot."
        ),
    },
    "DIRECTOR": {
        "label": "Director",
        "description": "Full production pipeline: model → light → animate → film.",
        "keywords": ("full production", "complete production", "entire production",
                     "whole film", "from scratch to final", "everything: model"),
        "tools": ("scene.inspect", "debug.diagnose"),
        "order": 5,
        "system_prompt": (
            "Director mode: run the full pipeline autonomously — subject, "
            "environment, materials, lighting, motion and a camera sequence — "
            "then verify. Keep each department's work coherent (one art "
            "direction, one frame range, one camera story)."
        ),
    },
    "OPTIMIZATION": {
        "label": "Optimization",
        "description": "Performance: analysis, decimation, cleanup, caps.",
        "keywords": ("optim", "decimat", "performance", "polycount", "poly count",
                     "retopo-lite", "clean up", "cleanup", "purge", "slow",
                     "lag", "too heavy", "reduce geo"),
        "tools": ("optimization.analyze", "optimization.decimate_scene",
                  "optimization.remove_doubles", "optimization.limit_subsurf",
                  "optimization.purge_unused"),
        "order": 90,
        "system_prompt": (
            "Optimization specialist. Measure first (optimization.analyze), "
            "then fix conservatively: cap subsurf, weld doubles, purge "
            "orphans. Decimate only heavy meshes and obvious problem cases — "
            "never destroy detail the user didn't ask to lose."
        ),
    },
    "DEBUG": {
        "label": "Debug",
        "description": "Diagnose and repair broken setups.",
        "keywords": ("fix", "broken", "error", "diagnos", "missing", "invalid",
                     "repair", "debug", "not working", "problem"),
        "tools": ("debug.diagnose", "debug.fix_common", "scene.inspect"),
        "order": 95,
        "system_prompt": (
            "Debug specialist. Diagnose before touching anything "
            "(debug.diagnose), apply only safe automatic fixes, re-scan to "
            "confirm, and clearly report anything needing manual help."
        ),
    },
}


def get_mode(mode_id: str) -> Optional[Dict[str, Any]]:
    return MODE_DEFS.get((mode_id or "").upper())


def list_modes() -> List[Dict[str, Any]]:
    return [{"id": key, **{k: v for k, v in value.items() if k != "system_prompt"}}
            for key, value in MODE_DEFS.items()]


def modes_manifest() -> List[Dict[str, Any]]:
    """JSON-serializable manifest including prompts (for external LLM clients)."""
    return [{"id": key, **value} for key, value in MODE_DEFS.items()]


def detect_modes(task: str) -> List[str]:
    """Return mode ids whose keywords appear in the task, in pipeline order."""
    lowered = (task or "").lower()
    hits = []
    for mode_id, info in MODE_DEFS.items():
        if mode_id in ("SMART", "DIRECTOR"):
            continue
        if any(kw in lowered for kw in info["keywords"]):
            hits.append(mode_id)
    # DIRECTOR only on strong explicit phrases.
    if any(kw in lowered for kw in MODE_DEFS["DIRECTOR"]["keywords"]):
        return ["DIRECTOR"]
    # "orbit" alone (no camera words) belongs to animation, not cutscene.
    camera_words = ("camera", "cinematic", "cutscene", "shot", "film")
    if "orbit" in lowered and not any(w in lowered for w in camera_words):
        hits = [h for h in hits if h != "CUTSCENE"]
        if "ANIMATION" not in hits:
            hits.append("ANIMATION")
    # fps tweaks belong to animation unless optimization is explicit.
    if hits == ["ANIMATION"] and "fps" in lowered:
        pass
    hits.sort(key=lambda m: MODE_DEFS[m]["order"])
    return hits
