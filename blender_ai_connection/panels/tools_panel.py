"""Tools browser sub-panel: inspect and manually run any tool."""

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


def _ensure_tools_cache(props) -> None:
    if len(props.tools_cache):
        return
    try:
        from ..tools import list_tools
        category = props.tool_category
        for tool in list_tools(None if category == "ALL" else
                               (None if category == "system" else category)):
            item = props.tools_cache.add()
            item.tool_id = tool["id"]
            item.label = tool["label"]
            item.category = tool["category"]
        if category in ("ALL", "system"):
            for tid, label in (("system.ping", "Ping bridge"),
                               ("system.tools", "List tools"),
                               ("system.modes", "List modes"),
                               ("agent.plan", "Plan task"),
                               ("agent.execute", "Execute task")):
                item = props.tools_cache.add()
                item.tool_id = tid
                item.label = label
                item.category = "system"
    except (ImportError, AttributeError, RuntimeError):
        pass


if HAS_BPY:

    class BAI_UL_tools(UIList):
        bl_idname = "BAI_UL_tools"

        def draw_item(self, _context, layout, _data, item, _icon, _acl, _acr):
            row = layout.row()
            row.label(text="", icon="TOOL_SETTINGS")
            row.label(text=f"{item.label}  [{item.category}]")

    class VIEW3D_PT_bai_tools(Panel):
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "AI Agent"
        bl_parent_id = "VIEW3D_PT_bai_agent"
        bl_label = "Tools"
        bl_options = {"DEFAULT_CLOSED"}

        def draw(self, context):
            from .main import wrap_text

            layout = self.layout
            props = getattr(context.scene, "blender_ai", None)
            if props is None:
                return
            _ensure_tools_cache(props)
            box = layout.box()
            box.label(text="TOOLS", icon="TOOL_SETTINGS")
            row = box.row(align=True)
            row.prop(props, "tool_category", text="")
            row.operator("bai.refresh_tools", text="", icon="FILE_REFRESH")
            box.template_list("BAI_UL_tools", "", props, "tools_cache",
                              props, "tool_index", rows=6)
            tool_id = ""
            if len(props.tools_cache):
                idx = max(0, min(props.tool_index, len(props.tools_cache) - 1))
                tool_id = props.tools_cache[idx].tool_id
            if tool_id:
                try:
                    from ..tools import get_tool
                    info = get_tool(tool_id) or {}
                    wrap_text(box, info.get("description", tool_id), width=40)
                    if props.show_tool_details and info.get("params"):
                        import json as _json
                        wrap_text(box, _json.dumps(info["params"], indent=1)[:1200],
                                  width=44)
                except ImportError:
                    pass
                box.prop(props, "show_tool_details", text="Show param spec")
                box.label(text="Params (JSON):")
                box.prop(props, "tool_params_json", text="")
                op = box.operator("bai.execute_tool", text=f"Run {tool_id}",
                                  icon="PLAY")
                op.tool_id = tool_id

else:
    class BAI_UL_tools:  # type: ignore
        pass

    class VIEW3D_PT_bai_tools:  # type: ignore
        pass
