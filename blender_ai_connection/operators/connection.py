"""Connection operators: start/stop bridge, check MCP health."""

from __future__ import annotations

try:
    import bpy
    from bpy.types import Operator
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False
    Operator = object  # type: ignore

from ..core import logger
from ..core import server as bridge
from ..mcp.health import check_mcp_status
from ..properties import get_props


def _sync_conn_props(props, running: bool, detail: str) -> None:
    props.server_running = running
    props.connection_status = "CONNECTED" if running else "DISCONNECTED"
    props.connection_detail = detail


if HAS_BPY:

    class BAI_OT_start_server(Operator):
        bl_idname = "bai.start_server"
        bl_label = "Start Server"
        bl_description = "Start the Blender <-> MCP TCP bridge"

        def execute(self, context):
            props = get_props(context)
            prefs = context.preferences.addons.get("blender_ai_connection")
            host = props.host if props else "127.0.0.1"
            port = props.port if props else 9876
            if prefs and hasattr(prefs, "preferences"):
                try:
                    logger.set_level(prefs.preferences.log_level)
                except (AttributeError, ValueError):
                    pass
            if props:
                props.connection_status = "CONNECTING"
                props.connection_detail = f"Binding {host}:{port}…"
            ok, msg = bridge.start(host, port)
            if props:
                _sync_conn_props(props, ok, msg)
                if not ok:
                    props.connection_status = "ERROR"
            logger.info(msg)
            self.report({"INFO"} if ok else {"ERROR"}, msg)
            return {"FINISHED"}

    class BAI_OT_stop_server(Operator):
        bl_idname = "bai.stop_server"
        bl_label = "Stop Server"
        bl_description = "Stop the Blender <-> MCP TCP bridge"

        def execute(self, context):
            ok, msg = bridge.stop()
            props = get_props(context)
            if props:
                _sync_conn_props(props, False, msg)
            logger.info(msg)
            self.report({"INFO"}, msg)
            return {"FINISHED"}

    class BAI_OT_check_mcp(Operator):
        bl_idname = "bai.check_mcp"
        bl_label = "Check MCP"
        bl_description = "Detect whether the MCP connection side is available"

        def execute(self, context):
            result = check_mcp_status()
            props = get_props(context)
            if props:
                props.mcp_status = result["status"]
                props.mcp_detail = (result["summary"] if result["status"] == "Ready"
                                    else result["setup_message"])
            if result["status"] == "Ready":
                logger.info(f"MCP check: Ready — {result['summary']}")
                self.report({"INFO"}, "MCP bridge ready.")
            else:
                logger.warning(f"MCP check: {result['status']} — {result['summary']}")
                self.report({"WARNING"}, f"MCP: {result['status']} (see panel for setup).")
            return {"FINISHED"}

else:
    class BAI_OT_start_server:  # type: ignore
        pass

    class BAI_OT_stop_server:  # type: ignore
        pass

    class BAI_OT_check_mcp:  # type: ignore
        pass
