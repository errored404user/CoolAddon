"""Main AI Agent panel: connection, mode, task, execution, results."""

from __future__ import annotations

try:
    import bpy
    from bpy.types import Panel, UIList
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False
    Panel = object  # type: ignore
    UIList = object  # type: ignore


def wrap_text(layout, text: str, width: int = 44, icon: str = "NONE"):
    """Blender labels don't wrap — split into multiple labels manually."""
    text = (text or "").replace("\t", " ")
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words, current = paragraph.split(" "), ""
        for word in words:
            probe = f"{current} {word}".strip()
            if len(probe) > width and current:
                lines.append(current)
                current = word
            else:
                current = probe
        if current or not lines:
            lines.append(current)
        if not paragraph:
            lines.append("")
    first = True
    for line in lines:
        if first and icon != "NONE":
            layout.label(text=line or " ", icon=icon)
            first = False
        else:
            layout.label(text=line or " ")


def mode_description(mode: str) -> str:
    try:
        from ..modes import get_mode
        info = get_mode(mode)
        if info:
            return str(info.get("description", ""))
    except (ImportError, AttributeError):
        pass
    fallback = {
        "SMART": "Auto-detects which specialist modes the task needs.",
        "MODELING": "Professional 3D modeling workflows.",
        "MATERIAL": "Shaders, PBR materials and textures.",
        "CHARACTER": "Characters, rigs, poses.",
        "ANIMATION": "Keyframes, motion and timing.",
        "ENVIRONMENT": "Complete environments.",
        "PROCEDURAL": "Procedural systems + Geometry Nodes.",
        "LIGHTING": "Cinematic and professional lighting.",
        "CUTSCENE": "Cinematic storytelling and cameras.",
        "DIRECTOR": "Full production pipeline in one run.",
        "OPTIMIZATION": "Performance and cleanup.",
        "DEBUG": "Diagnose and fix problems.",
    }
    return fallback.get(mode, "")


if HAS_BPY:

    class BAI_UL_history(UIList):
        bl_idname = "BAI_UL_history"

        def draw_item(self, _context, layout, _data, item, _icon, _acl, _acr):
            icon = {"OK": "CHECKMARK", "FAILED": "ERROR",
                    "RETRIED": "FILE_REFRESH", "SKIPPED": "X"}.get(item.status, "DOT")
            row = layout.row()
            row.label(text="", icon=icon)
            msg = (item.message or "")[:70]
            row.label(text=f"{item.name} — {msg}" if msg else item.name)

    class VIEW3D_PT_bai_agent(Panel):
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "AI Agent"
        bl_label = "AI Agent"
        bl_options = {"HEADER_LAYOUT_EXPAND"}

        def draw(self, context):
            layout = self.layout
            props = getattr(context.scene, "blender_ai", None)
            if props is None:
                layout.label(text="Properties unavailable.", icon="ERROR")
                return

            # ---- CONNECTION ------------------------------------------------
            box = layout.box()
            box.label(text="CONNECTION", icon="NETWORK_DRIVE")
            status_icon = {"CONNECTED": "CHECKMARK", "CONNECTING": "TIME",
                           "ERROR": "ERROR"}.get(props.connection_status, "X")
            box.label(text=f"Bridge: {props.connection_status.title()}",
                      icon=status_icon)
            wrap_text(box, props.connection_detail or "", width=40)
            row = box.row(align=True)
            row.prop(props, "host", text="Host")
            row.prop(props, "port", text="Port")
            row = box.row(align=True)
            start = row.operator("bai.start_server", text="Start Server",
                                 icon="PLAY")
            start.enabled = not props.server_running
            stop = row.operator("bai.stop_server", text="Stop", icon="SNAP_FACE")
            stop.enabled = props.server_running
            row = box.row(align=True)
            row.label(text=f"MCP: {props.mcp_status}", icon="PLUGIN")
            row.operator("bai.check_mcp", text="Check MCP")
            if props.mcp_status in ("Setup needed", "Bridge stopped") and props.mcp_detail:
                sub = box.box()
                wrap_text(sub, props.mcp_detail, width=40, icon="INFO")

            # ---- MODE ------------------------------------------------------
            box = layout.box()
            box.label(text="MODE", icon="MODIFIER")
            box.prop(props, "agent_mode", text="")
            wrap_text(box, mode_description(props.agent_mode), width=40)

            # ---- AI PROVIDER -----------------------------------------------
            box = layout.box()
            box.label(text="AI PROVIDER", icon="COMMUNITY")
            box.prop(props, "agent_source", text="")
            if props.agent_source == "LLM":
                box.prop(props, "llm_provider", text="")
                box.prop(props, "llm_model", text="Model")
                box.prop(props, "llm_api_key", text="Key")
                box.prop(props, "llm_base_url", text="Endpoint")
                box.prop(props, "llm_max_iters", text="Max steps")
                try:
                    from ..llm.providers import get_provider
                    info = get_provider(props.llm_provider) or {}
                    wrap_text(box, info.get("help", ""), width=40, icon="INFO")
                except ImportError:
                    pass
                if props.llm_status:
                    wrap_text(box, props.llm_status, width=40)

            # ---- TASK ------------------------------------------------------
            box = layout.box()
            box.label(text="TASK", icon="EDITMODE_HLT")
            box.prop(props, "agent_task", text="")
            row = box.row(align=True)
            row.operator("bai.load_example", text="Examples", icon="PRESET")
            row.operator("bai.clear_history", text="", icon="TRASH")
            start_row = box.row()
            start_row.scale_y = 2.0
            op = start_row.operator("bai.start_agent", text="START AGENT",
                                    icon="PLAY")
            op.enabled = props.agent_status != "RUNNING"
            if props.agent_status == "RUNNING":
                cancel_row = box.row()
                cancel_row.alert = True
                cancel_row.operator("bai.cancel_agent", text="Cancel",
                                    icon="CANCEL")

            # ---- EXECUTION -------------------------------------------------
            box = layout.box()
            box.label(text="EXECUTION", icon="TIME")
            agent_icon = {"RUNNING": "TIME", "DONE": "CHECKMARK",
                          "ERROR": "ERROR",
                          "CANCELLED": "CANCEL"}.get(props.agent_status, "DOT")
            box.label(text=f"Agent: {props.agent_status.title()}", icon=agent_icon)
            prog = box.row()
            prog.enabled = False
            prog.prop(props, "agent_progress", slider=True)
            if props.agent_current_step:
                wrap_text(box, props.agent_current_step, width=40, icon="RIGHTARROW")

            # ---- RESULTS ---------------------------------------------------
            box = layout.box()
            box.label(text="RESULTS", icon="OUTLINER_OB_EMPTY")
            if props.agent_summary:
                wrap_text(box, props.agent_summary[:600], width=40)
            else:
                box.label(text="No results yet.")
            if len(props.history):
                box.template_list("BAI_UL_history", "", props, "history",
                                  props, "tool_index", rows=4)

else:
    class BAI_UL_history:  # type: ignore
        pass

    class VIEW3D_PT_bai_agent:  # type: ignore
        pass
