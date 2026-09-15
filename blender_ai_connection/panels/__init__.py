"""N-panel UI for the AI Agent."""

try:
    import bpy  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False

if HAS_BPY:
    from .main import BAI_UL_history, VIEW3D_PT_bai_agent
    from .tools_panel import BAI_UL_tools, VIEW3D_PT_bai_tools
    from .logs_panel import BAI_UL_logs, VIEW3D_PT_bai_logs

    CLASSES = (
        BAI_UL_history,
        VIEW3D_PT_bai_agent,
        BAI_UL_tools,
        VIEW3D_PT_bai_tools,
        BAI_UL_logs,
        VIEW3D_PT_bai_logs,
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
