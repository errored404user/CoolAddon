"""Scene properties: connection state, agent state, logs, history."""

from __future__ import annotations

try:
    import bpy
    from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                           FloatProperty, IntProperty, StringProperty)
    from bpy.types import PropertyGroup
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False
    PropertyGroup = object  # type: ignore


MODE_ITEMS = [
    ("SMART", "Smart Agent", "Auto-select the right modes for the task"),
    ("MODELING", "Modeling", "Professional 3D modeling"),
    ("MATERIAL", "Material", "Shaders and textures"),
    ("CHARACTER", "Character", "Characters, rigging, poses"),
    ("ANIMATION", "Animation", "Keyframes, motion, rigs"),
    ("ENVIRONMENT", "Environment", "Complete environments"),
    ("PROCEDURAL", "Procedural", "Procedural generation + Geometry Nodes"),
    ("LIGHTING", "Lighting", "Cinematic and professional lighting"),
    ("CUTSCENE", "Cutscene", "Cinematic storytelling and cameras"),
    ("DIRECTOR", "Director", "Full production: model→animate→light→film"),
    ("OPTIMIZATION", "Optimization", "Performance and scene cleanup"),
    ("DEBUG", "Debug", "Diagnose and fix problems"),
]


if HAS_BPY:

    class BAI_LogEntry(PropertyGroup):
        level: StringProperty(default="INFO")
        time: StringProperty(default="")
        message: StringProperty(default="")

    class BAI_HistoryEntry(PropertyGroup):
        name: StringProperty(default="")
        status: StringProperty(default="OK")  # OK / FAILED / RETRIED / SKIPPED
        message: StringProperty(default="")
        duration_ms: IntProperty(default=0)

    class BAI_ToolItem(PropertyGroup):
        tool_id: StringProperty(default="")
        label: StringProperty(default="")
        category: StringProperty(default="")

    class BAI_Props(PropertyGroup):
        # Connection
        host: StringProperty(default="127.0.0.1")
        port: IntProperty(default=9876, min=1024, max=65535)
        server_running: BoolProperty(default=False)
        connection_status: EnumProperty(
            name="Connection",
            items=[("DISCONNECTED", "Disconnected", ""),
                   ("CONNECTING", "Connecting", ""),
                   ("CONNECTED", "Connected", ""),
                   ("ERROR", "Error", "")],
            default="DISCONNECTED",
        )
        connection_detail: StringProperty(default="Bridge stopped.")
        mcp_status: StringProperty(default="Unknown — press Check MCP.")
        mcp_detail: StringProperty(default="")
        # Agent
        agent_status: EnumProperty(
            name="Agent",
            items=[("IDLE", "Idle", ""), ("RUNNING", "Running", ""),
                   ("DONE", "Done", ""), ("CANCELLED", "Cancelled", ""),
                   ("ERROR", "Error", "")],
            default="IDLE",
        )
        agent_mode: EnumProperty(name="Mode", items=MODE_ITEMS, default="SMART")
        agent_task: StringProperty(
            name="Task", default="", subtype="NONE",
            description="Natural-language instruction for the agent",
        )
        agent_progress: FloatProperty(
            name="Progress", default=0.0, min=0.0, max=1.0, subtype="PERCENTAGE",
        )
        agent_current_step: StringProperty(default="")
        agent_summary: StringProperty(default="")
        # Agent source + LLM provider
        agent_source: EnumProperty(
            name="Agent Engine",
            items=[("BUILTIN", "Built-in planner", "Deterministic local planner (no API key)"),
                   ("LLM", "LLM provider", "Real AI model with tool calling (needs API key)")],
            default="BUILTIN",
        )
        llm_provider: EnumProperty(
            name="Provider",
            items=[("openai", "OpenAI", "ChatGPT models"),
                   ("deepseek", "DeepSeek", "DeepSeek chat models"),
                   ("gemini", "Gemini", "Google Gemini models"),
                   ("moonshot", "Kimi (Moonshot)", "Moonshot Kimi models"),
                   ("anthropic", "Claude (Anthropic)", "Anthropic Claude models"),
                   ("custom", "Custom / Proxy", "Any OpenAI-compatible endpoint")],
            default="openai",
        )
        llm_model: StringProperty(
            name="Model", default="",
            description="Empty = provider default model",
        )
        llm_api_key: StringProperty(
            name="API Key", default="", subtype="PASSWORD",
            description="Prefer environment variables; keys saved in .blend files are NOT secure",
        )
        llm_base_url: StringProperty(
            name="Endpoint", default="",
            description="Empty = provider default. Required for Custom, e.g. https://gpt.crax.lol/v1",
        )
        llm_max_iters: IntProperty(
            name="Max Steps", default=25, min=1, max=200,
            description="Max LLM tool iterations per task",
        )
        llm_status: StringProperty(default="")
        # Tools browser
        tool_category: EnumProperty(
            name="Category",
            items=[("ALL", "All", "")] + [(c, c.title(), "") for c in (
                "scene", "modeling", "material", "animation", "camera",
                "lighting", "rendering", "nodes", "physics", "project",
                "character", "environment", "procedural", "optimization",
                "debug", "cutscene")] +
                [("system", "System", "")],
            default="ALL",
        )
        tool_index: IntProperty(default=0)
        tool_params_json: StringProperty(default="{}")
        show_tool_details: BoolProperty(default=False)
        # Logs
        log_filter: EnumProperty(
            name="Level",
            items=[("ALL", "All", ""), ("INFO", "Info+", ""),
                   ("WARNING", "Warnings", ""), ("ERROR", "Errors", "")],
            default="ALL",
        )
        log_index: IntProperty(default=0)
        log_limit: IntProperty(default=300, min=20, max=2000)
        show_logs: BoolProperty(default=False, name="Show detailed logs")
        # Collections
        logs: CollectionProperty(type=BAI_LogEntry)
        history: CollectionProperty(type=BAI_HistoryEntry)
        tools_cache: CollectionProperty(type=BAI_ToolItem)

    CLASSES = (BAI_LogEntry, BAI_HistoryEntry, BAI_ToolItem, BAI_Props)

else:  # plain-python stubs so `import properties` never crashes outside Blender
    MODE_ITEMS = MODE_ITEMS

    class BAI_Props:  # type: ignore
        pass

    CLASSES = ()


def get_props(context=None):
    """Return the Scene property group (or None outside Blender)."""
    if not HAS_BPY:
        return None
    try:
        scene = context.scene if context is not None else bpy.context.scene
        return getattr(scene, "blender_ai", None)
    except (AttributeError, RuntimeError):
        return None


def register():
    if not HAS_BPY:
        return
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blender_ai = bpy.props.PointerProperty(type=BAI_Props)


def unregister():
    if not HAS_BPY:
        return
    try:
        del bpy.types.Scene.blender_ai
    except (AttributeError, RuntimeError):
        pass
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
