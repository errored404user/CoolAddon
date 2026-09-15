# Install Guide — Blender AI Connection

## 1) Blender addon (required)

**Option A — from folder (developers):**
1. Open Blender → Edit → Preferences → Add-ons → Install…
2. Pick any file inside `blender_ai_connection/` (Blender registers the folder),
   or copy/symlink the `blender_ai_connection` folder into your Blender
   `scripts/addons/` directory.
3. Enable **Blender AI Connection**, open the 3D Viewport Sidebar (`N`) →
   **AI Agent** tab.

**Option B — from ZIP:**
1. Zip the `blender_ai_connection/` folder (the folder itself, not the repo).
2. Blender → Preferences → Add-ons → Install… → select the ZIP → enable it.

2. Press **Start Server** (bridge defaults to `127.0.0.1:9876`).
3. Type a task, pick a mode (or leave **Smart Agent**), press **START AGENT**.

Requirements: Blender 3.6+ (4.x/5.x supported). No pip packages needed inside Blender.

## 2) MCP server (only for external AI control, e.g. Claude Desktop)

1. `pip install -r mcp_server/requirements.txt` (optional but recommended —
   without it a minimal JSON-RPC fallback is used).
2. Ensure the Blender bridge is running (step 1).
3. Add to your MCP client config (see `mcp_server/claude_config_example.json`):

```json
{"mcpServers": {"blender": {"command": "python",
  "args": ["/ABS/PATH/CoolAddon/mcp_server/server.py",
           "--host", "127.0.0.1", "--port", "9876"]}}}
```

4. Restart the MCP client. In Blender, **Check MCP** should report *Ready*.

## 3) Terminal CLI (optional, no MCP client needed)

```bash
python agent_runner/cli.py ping
python agent_runner/cli.py run --task "Create a futuristic robot" --mode SMART
```

## LLM provider keys (for ChatGPT / Claude / Gemini / DeepSeek / Kimi)

The AI chat *websites* cannot reach your computer — use each provider's **API key**:

| Provider | Env var | Get a key |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | platform.openai.com → API keys |
| DeepSeek | `DEEPSEEK_API_KEY` | platform.deepseek.com → API keys |
| Gemini | `GEMINI_API_KEY` | aistudio.google.com → Get API key |
| Kimi (Moonshot) | `MOONSHOT_API_KEY` | platform.moonshot.ai → API keys |
| Claude (Anthropic) | `ANTHROPIC_API_KEY` | console.anthropic.com → API keys |
| Custom / proxy | Key field or `BLENDER_AI_API_KEY` | your endpoint (e.g. `https://gpt.crax.lol/v1`) |

Set the env var **before starting Blender** (or paste into the panel Key field —
note panel keys are stored in the `.blend` file). Then: AI Agent tab →
AI PROVIDER → **LLM provider** → START AGENT. Terminal alternative:
`python agent_runner/llm.py run --provider deepseek --task "…"`.

## 4) Verify the install

```bash
python -m unittest discover -s tests -v
```

All tests are pure-Python and run without Blender.
