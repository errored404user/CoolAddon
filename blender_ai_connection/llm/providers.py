"""Provider registry: OpenAI, DeepSeek, Gemini, Kimi, Claude, Custom.

Pure Python. API keys are NEVER stored here — they come from the Blender
panel field, CLI flags, or environment variables (checked in that order).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


class LlmError(Exception):
    """Structured LLM failure (auth, network, bad request, ...)."""

    def __init__(self, code: str = "LLM_ERROR", message: str = "LLM request failed"):
        super().__init__(message)
        self.code = code
        self.message = message


PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "label": "OpenAI (ChatGPT models)",
        "format": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": ("OPENAI_API_KEY",),
        "key_required": True,
        "help": ("ChatGPT-class models (gpt-4o-mini, gpt-4o, o3, …). Defaults work as-is; "
                 "just add a key from platform.openai.com → API keys, or set OPENAI_API_KEY. "
                 "Usage is billed by OpenAI."),
    },
    "deepseek": {
        "label": "DeepSeek",
        "format": "openai",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_env": ("DEEPSEEK_API_KEY",),
        "key_required": True,
        "help": ("DeepSeek chat models at api.deepseek.com. Key from platform.deepseek.com → "
                 "API keys, or set DEEPSEEK_API_KEY."),
    },
    "gemini": {
        "label": "Google Gemini",
        "format": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "model": "gemini-2.0-flash",
        "key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "key_required": True,
        "help": ("Google Gemini models (gemini-2.0-flash, gemini-2.5-pro, …). Free/paid key from "
                 "aistudio.google.com → Get API key, or set GEMINI_API_KEY."),
    },
    "moonshot": {
        "label": "Kimi (Moonshot)",
        "format": "openai",
        "base_url": "https://api.moonshot.ai/v1",
        "model": "kimi-k2-0905",
        "key_env": ("MOONSHOT_API_KEY",),
        "key_required": True,
        "help": ("Moonshot Kimi models at api.moonshot.ai. Key from platform.moonshot.ai → API "
                 "keys, or set MOONSHOT_API_KEY. Adjust Model to a current Kimi id if needed."),
    },
    "anthropic": {
        "label": "Claude (Anthropic)",
        "format": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5",
        "key_env": ("ANTHROPIC_API_KEY",),
        "key_required": True,
        "help": ("Anthropic Claude models (claude-sonnet-4-5, claude-opus-4-…, …). Key from "
                 "console.anthropic.com → API keys, or set ANTHROPIC_API_KEY."),
    },
    "custom": {
        "label": "Custom / Proxy (OpenAI-compatible)",
        "format": "openai",
        "base_url": "",
        "model": "",
        "key_env": ("BLENDER_AI_API_KEY", "OPENAI_API_KEY"),
        "key_required": False,
        "help": ("Any OpenAI-compatible endpoint. Endpoint examples: a proxy such as "
                 "https://gpt.crax.lol/v1, Ollama http://localhost:11434/v1, LM Studio "
                 "http://localhost:1234/v1. Set Endpoint + Model (+ Key if your endpoint "
                 "needs one)."),
    },
}


def get_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    return PROVIDERS.get((provider_id or "").lower())


def list_providers() -> List[Dict[str, Any]]:
    return [{"id": pid, "label": info["label"], "format": info["format"],
             "base_url": info["base_url"], "model": info["model"],
             "key_env": list(info["key_env"])}
            for pid, info in PROVIDERS.items()]


def resolve_config(provider_id: str = "openai", model: str = "",
                   api_key: str = "", base_url: str = "") -> Dict[str, Any]:
    """Merge explicit values + provider defaults + env vars into a client cfg.

    Raises LlmError for unknown providers, missing endpoints, or missing
    required keys. The resolved cfg never logs/prints the key.
    """
    info = get_provider(provider_id or "openai")
    if info is None:
        raise LlmError("UNKNOWN_PROVIDER",
                       f"Unknown provider '{provider_id}'. "
                       f"Available: {', '.join(sorted(PROVIDERS))}.")
    key = (api_key or "").strip()
    if not key:
        for env in info["key_env"]:
            if os.environ.get(env, "").strip():
                key = os.environ[env].strip()
                break
    if info["key_required"] and not key:
        raise LlmError("MISSING_KEY",
                       f"{info['label']} needs an API key: fill the Key field or set "
                       f"{' / '.join(info['key_env'])}. {info['help']}")
    resolved_base = (base_url or "").strip() or info["base_url"]
    if not resolved_base:
        raise LlmError("MISSING_ENDPOINT",
                       f"{info['label']} needs an Endpoint URL. {info['help']}")
    resolved_model = (model or "").strip() or info["model"]
    if not resolved_model:
        raise LlmError("MISSING_MODEL",
                       f"{info['label']} needs a Model name. {info['help']}")
    return {"id": (provider_id or "openai").lower(), "label": info["label"],
            "format": info["format"], "base_url": resolved_base.rstrip("/"),
            "model": resolved_model, "api_key": key}
