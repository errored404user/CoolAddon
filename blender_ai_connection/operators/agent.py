"""Agent operators: START AGENT, cancel, history/logs, tool execution."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime

try:
    import bpy
    from bpy.props import EnumProperty, StringProperty
    from bpy.types import Operator
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False
    Operator = object  # type: ignore

from ..core import logger
from ..properties import get_props


EXAMPLE_TASKS = [
    ("ROBOT", "Detailed futuristic robot",
     "Create a detailed futuristic robot with metal materials.", "SMART"),
    ("CASTLE", "Medieval castle environment",
     "Create a medieval castle environment with stone walls, towers and torches.", "ENVIRONMENT"),
    ("METAL", "Realistic metal material",
     "Give the selected object a realistic brushed metal material.", "MATERIAL"),
    ("CAMSEQ", "Cinematic camera sequence",
     "Create a cinematic 3-camera sequence around the current scene.", "CUTSCENE"),
    ("FOREST", "Procedural forest",
     "Build a procedural forest using Geometry Nodes with 150 trees.", "PROCEDURAL"),
    ("LAB", "Sci-fi lab cinematic",
     "Create a complete sci-fi laboratory with lighting, materials and animated machinery.", "DIRECTOR"),
    ("FIX", "Inspect & fix scene",
     "Inspect the current scene and fix any obvious problems.", "DEBUG"),
    ("OPTIMIZE", "Optimize scene",
     "Optimize this scene for better performance.", "OPTIMIZATION"),
]


def _push_history(props, name: str, status: str, message: str, duration_ms: int = 0) -> None:
    try:
        item = props.history.add()
        item.name = name[:200]
        item.status = status
        item.message = message[:1000]
        item.duration_ms = int(duration_ms)
        while len(props.history) > 100:
            props.history.remove(0)
    except (AttributeError, RuntimeError, TypeError):
        pass


if HAS_BPY:

    class BAI_OT_start_agent(Operator):
        bl_idname = "bai.start_agent"
        bl_label = "Start Agent"
        bl_description = "Run the AI agent on the task above (non-blocking)"

        def execute(self, context):
            from ..agent import executor as _exec

            props = get_props(context)
            task = (props.agent_task or "").strip() if props else ""
            if not task:
                self.report({"ERROR"}, "Type a task first (or load an example).")
                return {"CANCELLED"}
            if props and props.agent_status == "RUNNING":
                self.report({"WARNING"}, "Agent is already running.")
                return {"CANCELLED"}
            mode = props.agent_mode if props else "SMART"
            ok, msg = _exec.start_async(task, mode=mode)
            if props:
                props.agent_status = "RUNNING" if ok else "ERROR"
                props.agent_summary = "" if ok else msg
            logger.info(msg)
            self.report({"INFO"} if ok else {"ERROR"}, msg)
            return {"FINISHED"}

    class BAI_OT_cancel_agent(Operator):
        bl_idname = "bai.cancel_agent"
        bl_label = "Cancel Agent"
        bl_description = "Request cancellation of the running agent"

        @classmethod
        def poll(cls, context):
            props = get_props(context)
            return bool(props and props.agent_status == "RUNNING")

        def execute(self, context):
            from ..agent import executor as _exec

            _exec.cancel()
            props = get_props(context)
            if props:
                props.agent_current_step = "Cancelling…"
            self.report({"INFO"}, "Agent cancellation requested.")
            return {"FINISHED"}

    class BAI_OT_clear_history(Operator):
        bl_idname = "bai.clear_history"
        bl_label = "Clear History"
        bl_description = "Clear the operation history"

        def execute(self, context):
            props = get_props(context)
            if props:
                props.history.clear()
                props.agent_summary = ""
            return {"FINISHED"}

    class BAI_OT_clear_logs(Operator):
        bl_idname = "bai.clear_logs"
        bl_label = "Clear Logs"
        bl_description = "Clear the log buffer"

        def execute(self, context):
            logger.clear()
            logger.info("Logs cleared.")
            return {"FINISHED"}

    class BAI_OT_export_logs(Operator):
        bl_idname = "bai.export_logs"
        bl_label = "Export Logs"
        bl_description = "Write recent logs to a text file next to the .blend (or temp dir)"

        def execute(self, context):
            lines = [f"[{e['time']}] {e['level']}: {e['message']}"
                     for e in logger.get_recent(500)]
            text = "\n".join(lines) or "(no logs)"
            try:
                path = bpy.path.abspath("//blender_ai_logs.txt")
                if path.startswith("//") or not path:
                    raise ValueError("unsaved blend")
            except (AttributeError, RuntimeError, ValueError):
                path = f"{tempfile.gettempdir()}/blender_ai_logs.txt"
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(f"Blender AI Connection logs — {datetime.now()}\n\n{text}\n")
            except OSError as exc:
                self.report({"ERROR"}, f"Could not write logs: {exc}")
                return {"CANCELLED"}
            self.report({"INFO"}, f"Logs exported: {path}")
            return {"FINISHED"}

    class BAI_OT_execute_tool(Operator):
        bl_idname = "bai.execute_tool"
        bl_label = "Execute Tool"
        bl_description = "Execute the selected tool with the JSON params below"

        tool_id: StringProperty(default="")  # type: ignore[assignment]

        def execute(self, context):
            import time as _time

            from ..core import dispatcher as _disp

            props = get_props(context)
            tool_id = self.tool_id or ""
            if props and not tool_id and len(props.tools_cache) > 0:
                idx = max(0, min(props.tool_index, len(props.tools_cache) - 1))
                tool_id = props.tools_cache[idx].tool_id
            if not tool_id:
                self.report({"ERROR"}, "No tool selected.")
                return {"CANCELLED"}
            raw = props.tool_params_json if props else "{}"
            try:
                params = json.loads(raw or "{}")
                if not isinstance(params, dict):
                    raise ValueError("params must be a JSON object")
            except ValueError as exc:
                self.report({"ERROR"}, f"Invalid params JSON: {exc}")
                return {"CANCELLED"}
            started = _time.time()
            response = _disp.dispatch({"id": "ui", "tool": tool_id,
                                       "params": params, "timeout": 120})
            ms = int((_time.time() - started) * 1000)
            if response.get("ok"):
                msg = json.dumps(response.get("result", {}), default=str)[:900]
                if props:
                    props.agent_summary = f"{tool_id} OK: {msg}"
                    _push_history(props, tool_id, "OK", msg, ms)
                logger.info(f"UI tool OK: {tool_id} ({ms}ms)")
                self.report({"INFO"}, f"{tool_id} OK ({ms}ms).")
            else:
                err = response.get("error", {})
                msg = f"[{err.get('code')}] {err.get('message')}"
                if props:
                    props.agent_summary = f"{tool_id} FAILED: {msg}"
                    _push_history(props, tool_id, "FAILED", msg, ms)
                logger.warning(f"UI tool FAILED: {tool_id}: {msg}")
                self.report({"ERROR"}, msg[:300])
            return {"FINISHED"}

    class BAI_OT_load_example(Operator):
        bl_idname = "bai.load_example"
        bl_label = "Load Example"
        bl_description = "Fill the task box with an example request"

        example: EnumProperty(
            name="Example",
            items=[(key, label, "") for key, label, _t, _m in EXAMPLE_TASKS],
            default="ROBOT",
        )  # type: ignore[assignment]

        def execute(self, context):
            props = get_props(context)
            for key, _label, task, mode in EXAMPLE_TASKS:
                if key == self.example and props:
                    props.agent_task = task
                    props.agent_mode = mode
                    break
            return {"FINISHED"}

        def invoke(self, context, _event):
            return context.window_manager.invoke_search_popup(self)

    class BAI_OT_refresh_tools(Operator):
        bl_idname = "bai.refresh_tools"
        bl_label = "Refresh Tools"
        bl_description = "Rebuild the tools browser list"

        def execute(self, context):
            from ..tools import list_tools

            props = get_props(context)
            if not props:
                return {"CANCELLED"}
            props.tools_cache.clear()
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
            props.tool_index = 0
            return {"FINISHED"}

else:
    class BAI_OT_start_agent:  # type: ignore
        pass

    class BAI_OT_cancel_agent:  # type: ignore
        pass

    class BAI_OT_clear_history:  # type: ignore
        pass

    class BAI_OT_clear_logs:  # type: ignore
        pass

    class BAI_OT_export_logs:  # type: ignore
        pass

    class BAI_OT_execute_tool:  # type: ignore
        pass

    class BAI_OT_load_example:  # type: ignore
        pass

    class BAI_OT_refresh_tools:  # type: ignore
        pass
