"""Blender operators (buttons) for the addon."""

try:
    import bpy  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False

if HAS_BPY:
    from .connection import BAI_OT_start_server, BAI_OT_stop_server, BAI_OT_check_mcp
    from .agent import (
        BAI_OT_start_agent,
        BAI_OT_cancel_agent,
        BAI_OT_clear_history,
        BAI_OT_clear_logs,
        BAI_OT_export_logs,
        BAI_OT_execute_tool,
        BAI_OT_load_example,
        BAI_OT_refresh_tools,
    )

    CLASSES = (
        BAI_OT_start_server,
        BAI_OT_stop_server,
        BAI_OT_check_mcp,
        BAI_OT_start_agent,
        BAI_OT_cancel_agent,
        BAI_OT_clear_history,
        BAI_OT_clear_logs,
        BAI_OT_export_logs,
        BAI_OT_execute_tool,
        BAI_OT_load_example,
        BAI_OT_refresh_tools,
    )
else:
    CLASSES = ()


def register():
    if not HAS_BPY:
        return
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    if not HAS_BPY:
        return
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
