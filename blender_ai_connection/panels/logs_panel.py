"""Logs sub-panel: detailed technical logs with level filtering."""

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


_LEVEL_RANK = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}


if HAS_BPY:

    class BAI_UL_logs(UIList):
        bl_idname = "BAI_UL_logs"

        def draw_item(self, _context, layout, _data, item, _icon, _acl, _acr):
            icon = {"ERROR": "ERROR", "WARNING": "ERROR",
                    "INFO": "INFO", "DEBUG": "DOT"}.get(item.level, "DOT")
            row = layout.row()
            row.label(text="", icon=icon)
            row.label(text=f"[{item.time}] {(item.message or '')[:90]}")

        def filter_items(self, context, data, propname):
            items = getattr(data, propname)
            flt_flags = [self.bitflag_filter_item] * len(items)
            flt_neworder = list(range(len(items)))
            props = getattr(context.scene, "blender_ai", None)
            want = getattr(props, "log_filter", "ALL") if props else "ALL"
            if want and want != "ALL":
                threshold = _LEVEL_RANK.get(want, 0)
                for i, item in enumerate(items):
                    if _LEVEL_RANK.get(item.level, 0) < threshold:
                        flt_flags[i] &= ~self.bitflag_filter_item
            # Newest last (insertion order) — keep stable order.
            return flt_flags, flt_neworder

    class VIEW3D_PT_bai_logs(Panel):
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "AI Agent"
        bl_parent_id = "VIEW3D_PT_bai_agent"
        bl_label = "Logs"
        bl_options = {"DEFAULT_CLOSED"}

        def draw(self, context):
            layout = self.layout
            props = getattr(context.scene, "blender_ai", None)
            if props is None:
                return
            box = layout.box()
            box.label(text="LOGS", icon="TEXT")
            row = box.row(align=True)
            row.prop(props, "log_filter", text="")
            row.operator("bai.clear_logs", text="", icon="TRASH")
            row.operator("bai.export_logs", text="", icon="EXPORT")
            box.template_list("BAI_UL_logs", "", props, "logs",
                              props, "log_index", rows=8)

else:
    class BAI_UL_logs:  # type: ignore
        pass

    class VIEW3D_PT_bai_logs:  # type: ignore
        pass
