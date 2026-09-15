# Install Guide — Blender AI Connection

## 0) Pick your Blender version

| Your Blender | Download this file | Install it in |
|---|---|---|
| **4.2 or newer** (incl. 5.x) | `dist/BlenderAIConnection-1.0.0.zip` | Preferences → **Extensions** → *Install from Disk* |
| **3.6 – 4.1** | `dist/BlenderAIConnection-legacy-1.0.0.zip` | Preferences → **Add-ons** → *Install…* |

Get the ZIPs from the repo's `dist/` folder (open the file on GitHub → Download),
or build them yourself: `python install/build.py`. No other downloads needed —
the addon itself requires **no pip packages**.

> ⚠️ Do **not** install the GitHub *repository* ZIP (`CoolAddon-....zip`) in Blender:
> it has the wrong layout and Blender will reject it. Only the `dist/` files work.

## 1) Blender 4.2+ (Extensions platform)

1. Edit → Preferences → **Extensions**.
2. Top-right arrow ▼ → **Install from Disk…** → select `BlenderAIConnection-1.0.0.zip`.
3. Find **Blender AI Connection**, tick the checkbox to enable it.
4. Approve the permission prompt (**network** = local bridge + LLM APIs,
   **files** = log export next to the `.blend`). Without approval it can't run.
5. Open the 3D Viewport, press `N` → **AI Agent** tab → **Start Server**.

## 2) Blender 3.6–4.1 (legacy Add-ons)

1. Edit → Preferences → **Add-ons** → **Install…** →
   select `BlenderAIConnection-legacy-1.0.0.zip`.
2. Enable **Blender AI Connection** (checkbox).
3. 3D Viewport → `N` → **AI Agent** tab → **Start Server**.

## 3) "It won't install" — troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| *"Archive does not contain an add-on/extension"*, or nothing happens | Wrong ZIP (repo ZIP, or a re-zipped folder) | Use the exact `dist/` file for your Blender (§0). Don't unzip/re-zip it |
| Installed, but not in the list | Looking in the wrong tab (4.2+: it's under **Extensions**, and search "AI") | Search "Blender AI"; check the *Install from Disk* completed without errors |
| Visible but nothing works / no N-panel tab | Not enabled, or side panel hidden | Tick the enable checkbox; in the 3D View press `N` and pick the **AI Agent** tab |
| Permission prompt denied | Extension blocked from network/files | Disable → enable again → **Allow** this time |
| Red error on enable | Environment-specific conflict | Window → *Toggle System Console*, copy the traceback (see §8) |
| Old version stuck / "already installed" | Stale copy in Blender's folders | Remove it in Preferences, **restart Blender**, install the new ZIP |
| "Legacy add-on" warning (4.2+) | You used the legacy ZIP | Harmless — but prefer the non-legacy `dist` file |
| *"Cannot load extension… Filenames starting with \_ are reserved"* | You opened the file in **Chrome/Edge** (`chrome://extensions`) — this project has **no** browser extension | Don't load anything into Chrome. Blender part → install the `dist/` ZIP **in Blender** (§1/§2); web UI → **run** `python dashboard/server.py`, then open the printed URL in any browser |
| Double-clicking the Start-Dashboard launcher flashes and closes | Python is missing, or the launcher is not inside the extracted repo folder | Install Python 3.10+ (Windows: tick "Add python.exe to PATH"), extract the whole repo ZIP, run the launcher from inside that folder |
| `dashboard/server.py` not found | You downloaded only the launcher file, not the repository | On GitHub: Code → Download ZIP, extract everything, run the launcher from inside the folder |
| Double-clicking `start-dashboard.sh` opens a text editor (Mac) | macOS will not execute scripts on double-click | Open Terminal in the folder, run `chmod +x start-dashboard.sh` once, then `./start-dashboard.sh` |
| Dashboard page loads but CONNECTION is red | The Blender bridge is not running | In Blender: AI Agent tab → Start Server, then reload the page |

**Manual install (bypasses the installer entirely):**
- 4.2+: unzip `BlenderAIConnection-1.0.0.zip` so that
  `.../extensions/user/blender_ai_connection/blender_manifest.toml` exists.
- 3.6–4.1: unzip the legacy ZIP so that
  `.../scripts/addons/blender_ai_connection/__init__.py` exists.

Base folders: Windows `%APPDATA%\Blender Foundation\Blender\<ver>\`,
macOS `~/Library/Application Support/Blender/<ver>/`,
Linux `~/.config/blender/<ver>/`. Restart Blender afterwards.

**Still stuck?** Tell us: Blender version (*Help → About*), the exact error text
from *Window → Toggle System Console*, and which ZIP you used.

## 4) MCP server (only for external AI control, e.g. Claude Desktop)

1. `pip install -r mcp_server/requirements.txt` (recommended — without it a
   minimal JSON-RPC fallback is used).
2. Ensure the Blender bridge is running (§1/§2, **Start Server**).
3. Add to your MCP client config (see `mcp_server/claude_config_example.json`):

```json
{"mcpServers": {"blender": {"command": "python",
  "args": ["/ABS/PATH/CoolAddon/mcp_server/server.py",
           "--host", "127.0.0.1", "--port", "9876"]}}}
```

4. Restart the MCP client. In Blender, **Check MCP** should report *Ready*.

## 5) Terminal CLI (optional, no MCP client needed)

```bash
python agent_runner/cli.py ping
python agent_runner/cli.py run --task "Create a futuristic robot" --mode SMART
```

## 6) LLM provider keys (for ChatGPT / Claude / Gemini / DeepSeek / Kimi)

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

## 7) Dashboard (recommended UI for Blender + providers)

Not a browser extension and not installed into Blender — a local web app you **run**:

Easiest: double-click **`Start-Dashboard.bat`** (Windows) or run
`./start-dashboard.sh` (macOS/Linux) — a browser tab opens automatically.

Manual equivalent:

```bash
python dashboard/server.py [--port 8899] [--open]
# open http://localhost:8899
```

Needs the Blender bridge running (§1/§2). Pick engine **Built-in** (free, offline)
or **LLM provider** (key via field or env var, §6), choose a mode, type a task,
press **START AGENT**. If the port is taken you'll get a clear message —
retry with `--port 8900`. Settings live in `dashboard/config/extension.json`.

## 8) Verify the install

```bash
python -m unittest discover -s tests -v   # pure-Python, no Blender needed
python install/build.py --check           # manifest + packaging validation
```
