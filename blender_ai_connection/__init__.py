"""Blender AI Connection — MCP-based AI production agent for Blender.

Install: zip the ``blender_ai_connection`` folder (or the repo root's addon
folder) and install via Edit > Preferences > Add-ons > Install.
UI lives in the 3D Viewport Sidebar (N) under the "AI Agent" tab.
"""

bl_info = {
    "name": "Blender AI Connection",
    "author": "CoolAddon",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "3D Viewport > Sidebar > AI Agent",
    "description": "MCP-based AI agent bridge: natural-language modeling, "
                   "materials, animation, lighting, cutscenes and more.",
    "category": "AI",
}

from . import preferences  # noqa: E402
from . import properties  # noqa: E402
from . import operators  # noqa: E402
from . import panels  # noqa: E402
from .core import logger  # noqa: E402


def _delayed_autostart():
    """Start the bridge shortly after load when the user opted in."""
    try:
        import bpy  # type: ignore

        prefs = bpy.context.preferences.addons.get("blender_ai_connection")
        if prefs and getattr(prefs.preferences, "auto_start", False):
            from .core import server as _server

            host = getattr(prefs.preferences, "host", "127.0.0.1")
            port = getattr(prefs.preferences, "port", 9876)
            ok, msg = _server.start(host, port)
            for scene in bpy.data.scenes:
                props = getattr(scene, "blender_ai", None)
                if props is not None:
                    props.host = host
                    props.port = port
                    props.server_running = ok
                    props.connection_status = "CONNECTED" if ok else "ERROR"
                    props.connection_detail = msg
            logger.info(f"Auto-start bridge: {msg}")
    except (AttributeError, RuntimeError, ImportError) as exc:
        logger.warning(f"Auto-start skipped: {exc}")
    return None


def register():
    preferences.register()
    properties.register()
    operators.register()
    panels.register()
    # Apply preferred log level.
    try:
        import bpy  # type: ignore

        prefs = bpy.context.preferences.addons.get("blender_ai_connection")
        if prefs and hasattr(prefs, "preferences"):
            logger.set_level(getattr(prefs.preferences, "log_level", "INFO"))
        try:
            bpy.app.timers.register(_delayed_autostart, first_interval=1.0)
        except (AttributeError, RuntimeError, ValueError):
            pass
    except ImportError:
        pass
    logger.info("Blender AI Connection registered.")


def unregister():
    # Stop agent + bridge first so background threads never outlive the addon.
    try:
        from .agent import executor as _exec

        _exec.cancel()
        _exec.shutdown_timer()
    except (ImportError, AttributeError, RuntimeError):
        pass
    try:
        from .core import server as _server

        if _server.is_running():
            _server.stop()
    except (ImportError, AttributeError, RuntimeError, OSError):
        pass
    panels.unregister()
    operators.unregister()
    properties.unregister()
    preferences.unregister()
    logger.info("Blender AI Connection unregistered.")
