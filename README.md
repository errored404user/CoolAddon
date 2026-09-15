# Blender AI Connection

A professional, extensible **AI production agent for Blender**: give natural-language
instructions, and the agent plans and executes real Blender work — modeling, materials,
rigging, animation, environments, lighting, physics, cutscenes — through a reliable
bridge that external AIs can also drive via **MCP**.

```
 Natural language                  Blender
 ┌──────────────┐  MCP / TCP bridge  ┌────────────────────────────┐
 │ You / Claude /│ ─── stdio ───►     │  AI Agent panel            │
 │ any MCP agent │  mcp_server/  │    │  Planner → Executor → Tools│──► bpy
 │ (or START     │  server.py    │    │  89 tools · 12 modes       │
 │  AGENT in UI) │ ◄── results ──    │  verify + auto-recovery    │
 └──────────────┘  127.0.0.1:9876    └────────────────────────────┘
```

## Highlights

- **89 real Blender tools** across 16 categories (scene → cutscene), all validated,
  permission-checked and exception-safe.
- **12 AI modes**: Smart Agent (auto-routing), Modeling, Material, Character,
  Animation, Environment, Procedural, Lighting, Cutscene, Director, Optimization, Debug.
- **Built-in agent**: type a task, press **START AGENT** — non-blocking execution with
  progress, history, logs and one-click examples. No external AI or setup required.
- **MCP bridge**: control Blender from Claude Desktop or any MCP client
  (`tools/list` + `tools/call`), with a dependency-free fallback backend.
- **Agent CLI**: drive Blender from a terminal (`plan`, `run`, `tool`, `ping`).
- **Verify + recover**: plans end with scene verification; failures get safe automatic
  fixes (fuzzy names, degenerate aims, empty selections) and one retry.
- **Extensible**: a new tool is one decorated function; a new mode is one registry
  entry + one planner function. Nothing else changes.

## Quickstart

### A. Blender only (2 minutes, no other setup)

1. Blender → Preferences → Add-ons → Install… → zip the `blender_ai_connection/`
   folder → enable **Blender AI Connection**. (Blender 3.6+, incl. 4.x/5.x.)
2. 3D Viewport → Sidebar (`N`) → **AI Agent** tab → **Start Server**.
3. Type a task (or pick an **Examples** preset), leave mode on **Smart Agent**,
   press **START AGENT**.

Try: *"Create a detailed futuristic robot."* · *"Build a procedural forest using
Geometry Nodes."* · *"Create a 10-second cinematic of the scene."*

### B. External AI via MCP (Claude Desktop, …)

1. Do step A (bridge must be listening).
2. `pip install -r mcp_server/requirements.txt` (recommended; a minimal backend
   works without it).
3. Add to your MCP client config (full example in
   `mcp_server/claude_config_example.json`):

```json
{"mcpServers": {"blender": {"command": "python", "args": [
  "/ABS/PATH/CoolAddon/mcp_server/server.py", "--host", "127.0.0.1", "--port", "9876"]}}}
```

4. Restart the client. In Blender, **Check MCP** reports *Ready* (or exact setup steps).

### C. Terminal (no MCP client)

```bash
python agent_runner/cli.py ping
python agent_runner/cli.py plan --task "Create a medieval castle environment"
python agent_runner/cli.py run   --task "Create a medieval castle environment" --mode ENVIRONMENT
python agent_runner/cli.py tool  --name scene.inspect --params '{}'
```

### D. Use ChatGPT / Claude / Gemini / DeepSeek / Kimi models

Web chat pages (chatgpt.com, claude.ai, gemini.google.com, …) **cannot** reach
your PC, so they can't use MCP directly — but their underlying **models can
drive Blender through API keys**, which this addon supports natively:

| Provider | Models | Key from | Endpoint default |
|---|---|---|---|
| OpenAI | gpt-4o-mini, gpt-4o, o3, … | `OPENAI_API_KEY` | `api.openai.com/v1` |
| DeepSeek | deepseek-chat, … | `DEEPSEEK_API_KEY` | `api.deepseek.com` |
| Gemini | gemini-2.0-flash, … | `GEMINI_API_KEY` | `generativelanguage.googleapis.com` |
| Kimi (Moonshot) | kimi-k2-…, … | `MOONSHOT_API_KEY` | `api.moonshot.ai/v1` |
| Claude (Anthropic) | claude-sonnet-4-5, … | `ANTHROPIC_API_KEY` | `api.anthropic.com` |
| Custom / Proxy | whatever yours serves | Key field / `BLENDER_AI_API_KEY` | you set it, e.g. `https://gpt.crax.lol/v1`, Ollama, LM Studio |

**In Blender:** AI Agent tab → **AI PROVIDER** → engine **LLM provider** → pick
provider, model (empty = default), paste key (or set the env var — safer),
START AGENT. HTTP runs on a background thread; every tool call still executes
on the main thread through the validated dispatcher.

**In terminal:** `python agent_runner/llm.py run --provider deepseek --task "…"`.

Notes: API usage is billed by each provider. Keys in the panel are saved into
`.blend` files — prefer env vars. Microsoft Copilot (copilot.ai) has **no
public API**, so it can't be added as a provider.

## The panel

| Section | What it does |
|---|---|
| **CONNECTION** | Bridge host/port, Start/Stop, MCP status + **Check MCP** (setup help when missing) |
| **MODE** | 12-mode selector with a description of each |
| **TASK** | Natural-language input, example presets, big **START AGENT** + Cancel |
| **EXECUTION** | Live progress bar + current step (`Creating model…`, `Verifying scene…`) |
| **RESULTS** | One-line summary + operation history (OK / retried / failed / skipped) |
| **Tools** (sub-panel) | Browse all 89 tools, inspect param specs, run any tool with JSON params |
| **Logs** (sub-panel) | Detailed technical logs with level filter, clear + export |

## Architecture

```
blender_ai_connection/          # Blender addon (zip this to install)
  __init__.py                   # bl_info + registration + auto-start
  preferences.py  properties.py # config UI + scene state (status/mode/logs/history)
  operators/  panels/           # buttons + N-panel UI
  core/
    server.py                   # TCP bridge: I/O on threads, bpy on main thread via timer
    dispatcher.py               # validation → routing → structured errors (never raises)
    protocol.py                 # newline-JSON schema (shared, pure python)
    logger.py                   # ring buffer + console + panel mirror
  tools/  (89 tools)            # scene modeling material animation camera lighting
                                # rendering nodes physics project character
                                # environment procedural optimization debug cutscene
  modes/                        # 12 mode defs: keywords, tools, LLM system prompts
  agent/
    planner.py                  # task text → ordered, dependency-safe plan
    executor.py                 # sync (bridge) + async timer (UI) execution, $refs, retry
    recovery.py                 # safe auto-fixes
  mcp/health.py                 # MCP availability detection + setup guidance
  utils/blender_utils.py        # safe bpy wrappers
mcp_server/                     # stdio MCP server → TCP bridge (SDK + minimal backends)
agent_runner/cli.py             # terminal client (plan/run/tool/ping/tools/modes)
skills/                         # 8 agent playbooks (modeling…director) for LLMs
config/config.json              # defaults: endpoint, limits, log level, permissions
tests/ install/                 # pure-python unittest suite + install guide
```

**Protocol** (TCP `127.0.0.1:9876`, newline-delimited JSON):
`{"id","tool","params","timeout"}` →
`{"id","ok","result","error":{"code","message","details"},"duration_ms"}`.
Special system tools: `system.ping`, `system.tools`, `system.modes`,
`agent.plan`, `agent.execute`.

## Tool catalog (89)

| Category | Tools |
|---|---|
| scene (6) | inspect, clear, organize, select, delete, set_active |
| modeling (14) | create_primitive, transform, duplicate, join, boolean, add_modifier, apply_modifier, bevel, subdivide, symmetry, set_shade, extrude, decimate, merge_by_distance |
| material (6) | list, create (13 PBR presets), assign, set_principled, create_node_setup, remove |
| animation (7) | set_timeline, set_keyframe, animate_transform, set_interpolation, create_loop, clear_keyframes, list_actions |
| camera (6) | create, look_at, track_to, set_active, create_sequence, list |
| lighting (4) | create, setup_preset (7 cinematic looks), set_world (+HDRI), list |
| rendering (4) | configure, set_output, render (still), info |
| nodes (6) | create_geonodes (3 presets), add_node, link_nodes, inspect_tree, list_trees, apply_to_object |
| physics (7) | add_rigid_body, add_cloth, add_collision, add_force, set_gravity, bake_to_keyframes, summary |
| project (5) | save, export (FBX/OBJ/GLB/GLTF/STL), import_model, create_collection, move_to_collection |
| character (6) | create_armature, add_ik, parent_with_weights, create_pose, add_constraint, build_simple_humanoid |
| environment (4) | create_terrain, scatter_objects, create_preset (8 themes), set_atmosphere |
| procedural (3) | create_building, create_stairs, array_distribute |
| optimization (5) | analyze, decimate_scene, remove_doubles, limit_subsurf, purge_unused |
| debug (2) | diagnose (+auto_fix), fix_common |
| cutscene (4) | create_shot (6 camera moves), build_sequence, add_camera_shake, list_shots |

Full param specs: Blender **Tools** sub-panel → *Show param spec*, or `system.tools`.

## Modes

Smart Agent routes automatically through: model → materials → rig → environment →
physics → animation → lighting → camera → render → verify. Explicit modes run their
specialty only (Cutscene still adds light if the scene has none; Director runs the
whole pipeline). Every mode ships an LLM `system_prompt` in `system.modes`.

## Configuration

`config/config.json` holds defaults; Blender-side overrides live in
Preferences → *Blender AI Connection* (host/port, log level, max steps/retries,
step timeout, auto-start, denied-tools list). Denied tools return `TOOL_DENIED`
instead of running.

## For developers

**Add a tool** — one function, zero boilerplate elsewhere:

```python
# in blender_ai_connection/tools/my_tools.py (import it from tools/__init__.py)
from .base import register_tool

@register_tool("mydomain.magic", "modeling", "Do magic",
               "What it does.", params={"target": {"type": "string", "required": True}})
def magic(params):
    from ..utils import blender_utils as BU
    obj = BU.require_object(params["target"])  # structured errors, no crashes
    ...
    return {"name": obj.name}
```

It instantly appears in the UI browser, `system.tools`, MCP `tools/list`, and the CLI.

**Add a mode** — one entry in `modes/__init__.py` (`MODE_DEFS`: keywords, tools,
prompt) + one `plan_<mode>` builder in `agent/planner.py` + enum item in
`properties.py`.

**Tests** (pure Python, no Blender needed):

```bash
python -m unittest discover -s tests -v
```

## Honest limitations

- No sculpt-mode automation, full retopology, or fluid/smoke sim setup yet (rigid,
  cloth, collision, forces, gravity + rigid→keyframe baking are implemented).
- Rendering covers stills + full configuration; animation-sequence rendering and
  VSE editing are not included.
- Tool `timeout` is enforced at the network layer; a running Blender operation
  itself runs to completion (preempting `bpy` would risk corruption).
- The minimal MCP backend covers `initialize` / `tools/list` / `tools/call` /
  `ping`; install `mcp` for the complete SDK surface.

These are E02architected extension points (new tools/modes drop in cleanly) — see
`skills/` + the developer guide above.
