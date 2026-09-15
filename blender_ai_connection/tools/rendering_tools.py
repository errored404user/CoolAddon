"""Rendering tools: engines, resolution, output, still renders."""

from __future__ import annotations

import os
from typing import Any, Dict

from .base import ToolError, register_tool, require_bpy
from ..utils import blender_utils as BU

ENGINES = ("CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH")
IMAGE_FORMATS = ("PNG", "JPEG", "OPEN_EXR", "TIFF", "BMP")


@register_tool("rendering.configure", "rendering", "Configure renderer",
               "Set engine, resolution, samples, denoise, transparency, motion blur.",
               params={
                   "engine": {"type": "string", "default": None,
                              "choices": list(ENGINES)},
                   "resolution": {"type": "list", "default": None,
                                  "description": "[width, height]"},
                   "resolution_percentage": {"type": "int", "default": None},
                   "samples": {"type": "int", "default": None},
                   "use_denoise": {"type": "bool", "default": None},
                   "film_transparent": {"type": "bool", "default": None},
                   "motion_blur": {"type": "bool", "default": None},
               })
def render_configure(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    scene = BU.ctx_scene()
    render = scene.render
    changed = []
    if params.get("engine"):
        engine = params["engine"]
        if engine == "BLENDER_EEVEE_NEXT":
            # 4.x unified Eevee name; fall back gracefully on 3.x.
            try:
                render.engine = engine
            except TypeError:
                render.engine = "BLENDER_EEVEE"
        else:
            render.engine = engine
        changed.append(f"engine={render.engine}")
    if params.get("resolution") is not None:
        res = params["resolution"]
        if len(res) != 2:
            raise ToolError("INVALID_PARAMS", "resolution must be [width, height].")
        render.resolution_x = max(8, int(res[0]))
        render.resolution_y = max(8, int(res[1]))
        changed.append(f"resolution={render.resolution_x}x{render.resolution_y}")
    if params.get("resolution_percentage") is not None:
        render.resolution_percentage = max(1, min(int(params["resolution_percentage"]), 400))
        changed.append(f"percentage={render.resolution_percentage}")
    if params.get("samples") is not None:
        samples = max(1, min(int(params["samples"]), 100000))
        try:
            if render.engine == "CYCLES":
                scene.cycles.samples = samples
            elif hasattr(scene, "eevee"):
                scene.eevee.taa_render_samples = samples
        except (AttributeError, TypeError):
            pass
        changed.append(f"samples={samples}")
    if params.get("use_denoise") is not None:
        try:
            if render.engine == "CYCLES":
                scene.cycles.use_denoising = bool(params["use_denoise"])
                changed.append(f"denoise={scene.cycles.use_denoising}")
        except (AttributeError, TypeError):
            pass
    if params.get("film_transparent") is not None:
        render.film_transparent = bool(params["film_transparent"])
        changed.append(f"transparent={render.film_transparent}")
    if params.get("motion_blur") is not None:
        render.use_motion_blur = bool(params["motion_blur"])
        changed.append(f"motion_blur={render.use_motion_blur}")
    return {"changed": changed, "engine": render.engine}


@register_tool("rendering.set_output", "rendering", "Set render output",
               "Set output path and image format (creates folders).",
               params={
                   "filepath": {"type": "string", "default": None},
                   "format": {"type": "string", "default": None,
                              "choices": list(IMAGE_FORMATS)},
               })
def render_output(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    scene = BU.ctx_scene()
    render = scene.render
    if params.get("filepath"):
        path = str(params["filepath"])
        folder = os.path.dirname(os.path.abspath(path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        render.filepath = path
    if params.get("format"):
        render.image_settings.file_format = params["format"]
    return {"filepath": render.filepath,
            "format": render.image_settings.file_format}


@register_tool("rendering.render", "rendering", "Render still",
               "Render a single frame to disk (blocking — may take a while).",
               params={
                   "frame": {"type": "string", "default": "current",
                             "description": "'current' or a frame number"},
                   "filepath": {"type": "string", "default": ""},
               })
def render_still(params: Dict[str, Any]) -> Dict[str, Any]:
    bpy = require_bpy()
    scene = BU.ctx_scene()
    frame = params.get("frame", "current")
    if str(frame).lower() != "current":
        try:
            scene.frame_set(int(frame))
        except (TypeError, ValueError):
            raise ToolError("INVALID_PARAMS", "frame must be 'current' or a number.")
    if params.get("filepath"):
        out = render_output({"filepath": params["filepath"], "format": None})
        path = out["filepath"]
    else:
        path = scene.render.filepath or "/tmp/blender_ai_render.png"
        if not os.path.splitext(path)[1]:
            path = path.rstrip("/") + ".png"
        folder = os.path.dirname(os.path.abspath(path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        scene.render.filepath = path
    try:
        bpy.ops.render.render(animation=False, write_still=True)
    except RuntimeError as exc:
        raise ToolError("TOOL_FAILED", f"Render failed: {exc}")
    return {"rendered_frame": scene.frame_current, "filepath": scene.render.filepath,
            "engine": scene.render.engine}


@register_tool("rendering.info", "rendering", "Render info",
               "Report current render configuration.",
               params={})
def render_info(params: Dict[str, Any]) -> Dict[str, Any]:
    require_bpy()
    scene = BU.ctx_scene()
    render = scene.render
    info = {"engine": render.engine,
            "resolution": [render.resolution_x, render.resolution_y],
            "percentage": render.resolution_percentage,
            "filepath": render.filepath,
            "format": render.image_settings.file_format,
            "film_transparent": render.film_transparent,
            "motion_blur": render.use_motion_blur}
    try:
        if render.engine == "CYCLES":
            info["samples"] = scene.cycles.samples
            info["denoise"] = scene.cycles.use_denoising
            info["device"] = scene.cycles.device
    except AttributeError:
        pass
    return info
