"""Addon preferences (Blender-side configuration UI)."""

from __future__ import annotations

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
    from bpy.types import AddonPreferences
    HAS_BPY = True
except ImportError:  # pragma: no cover - allows plain-python import
    bpy = None  # type: ignore
    HAS_BPY = False
    AddonPreferences = object  # type: ignore


class BlenderAIAddonPreferences(AddonPreferences if HAS_BPY else object):
    bl_idname = "blender_ai_connection"

    host: StringProperty(
        name="Bridge Host",
        description="Host the Blender bridge server listens on",
        default="127.0.0.1",
    ) if HAS_BPY else None
    port: IntProperty(
        name="Bridge Port",
        description="TCP port for the Blender <-> MCP bridge",
        default=9876, min=1024, max=65535,
    ) if HAS_BPY else None
    log_level: EnumProperty(
        name="Log Level",
        items=[("DEBUG", "Debug", ""), ("INFO", "Info", ""),
               ("WARNING", "Warning", ""), ("ERROR", "Error", "")],
        default="INFO",
    ) if HAS_BPY else None
    step_timeout: IntProperty(
        name="Step Timeout (s)", default=120, min=5, max=1800,
    ) if HAS_BPY else None
    max_steps: IntProperty(
        name="Max Steps / Task", default=60, min=1, max=500,
    ) if HAS_BPY else None
    max_retries: IntProperty(
        name="Retries / Step", default=1, min=0, max=5,
    ) if HAS_BPY else None
    auto_start: BoolProperty(
        name="Auto-start bridge on load",
        description="Start the TCP bridge automatically when Blender loads",
        default=False,
    ) if HAS_BPY else None
    denied_tools: StringProperty(
        name="Denied Tools",
        description="Comma-separated tool ids the agent is NOT allowed to run",
        default="",
    ) if HAS_BPY else None

    def draw(self, context):
        if not HAS_BPY:
            return
        layout = self.layout
        layout.label(text="Blender AI Connection — bridge & agent settings")
        box = layout.box()
        row = box.row(align=True)
        row.prop(self, "host")
        row.prop(self, "port")
        row = box.row(align=True)
        row.prop(self, "log_level")
        row.prop(self, "auto_start")
        box = layout.box()
        box.label(text="Agent execution limits")
        row = box.row(align=True)
        row.prop(self, "max_steps")
        row.prop(self, "max_retries")
        row.prop(self, "step_timeout")
        box = layout.box()
        box.label(text="Tool permissions")
        box.prop(self, "denied_tools")


def register():
    if HAS_BPY:
        bpy.utils.register_class(BlenderAIAddonPreferences)


def unregister():
    if HAS_BPY:
        bpy.utils.unregister_class(BlenderAIAddonPreferences)
