# Blender AI Extension — Control Center

A local web dashboard that connects **Blender** and **AI providers** in one place.
This is the `extension/` component of the project architecture: the
`blender_ai_connection/` addon runs *inside* Blender, while this extension runs
*next to* it (browser UI + job server).

Stdlib-only Python + vanilla JS — no installs, no build step, works offline
(except for cloud LLM calls, obviously).

## Run it

```bash
python extension/server.py [--port 8899] [--blender-port 9876]
# open http://localhost:8899
```

1. In Blender: AI Agent tab → **Start Server** (the bridge).
2. Here: CONNECTION turns green. Pick engine (**Built-in planner** = free,
   offline; **LLM provider** = real AI model), mode, task → **START AGENT**.
3. Watch EXECUTION stream step-by-step; RESULTS + JOBS keep history.

## What it does

| Area | Behavior |
|---|---|
| CONNECTION | Blender host/port, live reachability, Blender version |
| AI PROVIDER | Engine switch; provider/model/key/endpoint for OpenAI, DeepSeek, Gemini, Kimi, Claude, custom proxies. Keys stay in server memory only, never in job history |
| MODE | All 12 modes with descriptions |
| TASK | Free text + example presets + plan preview (works even with Blender offline) |
| EXECUTION | Per-step progress with OK / retried / failed / skipped events |
| RESULTS / JOBS | Final summaries + past runs (click to re-open) |
| TOOLS | Searchable browser over all 89 tools; run any tool with JSON params |
| MCP | `mcp` package status + copy-paste Claude Desktop config snippet |

## Notes

- The built-in engine plans locally (`agent.plan` logic) and executes each step
  over the bridge with the same auto-recovery as the in-Blender agent.
- The LLM engine runs the shared `llm.agent_loop` against the bridge — identical
  behavior to `agent_runner/llm.py`, with live browser progress.
- `extension/config/extension.json` holds server/blender/default settings.
  Keys are never written anywhere — use env vars or paste per session.
