"""Universal LLM provider layer (pure Python, stdlib only).

Lets real AI models — OpenAI/ChatGPT, DeepSeek, Gemini, Kimi/Moonshot,
Claude/Anthropic, or any OpenAI-compatible endpoint (proxies, Ollama,
LM Studio) — drive Blender through the same validated tool system the
built-in planner uses. No third-party packages, so it runs both inside
Blender and in standalone scripts.
"""

from .providers import LlmError, get_provider, list_providers, resolve_config  # noqa: F401
from .agent_loop import LoopAbort, llm_manifest, run_loop  # noqa: F401
