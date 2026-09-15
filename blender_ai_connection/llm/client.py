"""Minimal multi-format LLM HTTP client (stdlib only: urllib).

Internal message format (normalized across providers):
    {"role": "system",      "text": str}
    {"role": "user",        "text": str}
    {"role": "assistant",   "text": str, "tool_calls": [{"id","name","args"}]}
    {"role": "tool",        "text": str, "tool_call_id": str, "tool_name": str}

chat() returns {"text": str, "tool_calls": [{"id","name","args"}]}.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List

from .providers import LlmError
from .schema import anthropic_tools, gemini_tools, openai_tools


def _parse_args(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


# ---------------------------------------------------------------------------
# OpenAI chat-completions format (OpenAI, DeepSeek, Moonshot, custom/proxies)
# ---------------------------------------------------------------------------

def build_openai_payload(cfg: Dict[str, Any], messages: List[Dict[str, Any]],
                         manifest: List[Dict[str, Any]],
                         max_tokens: int = 2048,
                         temperature: float = 0.2) -> Dict[str, Any]:
    converted = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            converted.append({"role": "system", "content": msg.get("text", "")})
        elif role == "user":
            converted.append({"role": "user", "content": msg.get("text", "")})
        elif role == "assistant":
            entry: Dict[str, Any] = {"role": "assistant",
                                     "content": msg.get("text") or ""}
            calls = msg.get("tool_calls") or []
            if calls:
                entry["tool_calls"] = [
                    {"id": c.get("id", f"call_{i}"), "type": "function",
                     "function": {"name": c.get("name", ""),
                                  "arguments": json.dumps(c.get("args", {}))}}
                    for i, c in enumerate(calls)]
            converted.append(entry)
        elif role == "tool":
            converted.append({"role": "tool",
                              "tool_call_id": msg.get("tool_call_id", ""),
                              "content": msg.get("text", "")})
    return {"model": cfg["model"], "messages": converted,
            "tools": openai_tools(manifest), "tool_choice": "auto",
            "temperature": temperature, "max_tokens": max_tokens}


def parse_openai_response(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise LlmError("BAD_RESPONSE", "Unrecognized OpenAI-style response.")
    calls = []
    for call in message.get("tool_calls") or []:
        func = call.get("function", {}) or {}
        calls.append({"id": call.get("id", f"call_{len(calls)}"),
                      "name": func.get("name", ""),
                      "args": _parse_args(func.get("arguments"))})
    return {"text": message.get("content") or "", "tool_calls": calls}


# ---------------------------------------------------------------------------
# Anthropic Messages format (Claude)
# ---------------------------------------------------------------------------

def build_anthropic_payload(cfg: Dict[str, Any], messages: List[Dict[str, Any]],
                            manifest: List[Dict[str, Any]],
                            max_tokens: int = 2048,
                            temperature: float = 0.2) -> Dict[str, Any]:
    system_parts = [m.get("text", "") for m in messages if m.get("role") == "system"]
    converted: List[Dict[str, Any]] = []
    pending_tools: List[Dict[str, Any]] = []

    def flush_tools():
        if pending_tools:
            converted.append({"role": "user", "content": list(pending_tools)})
            pending_tools.clear()

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue
        if role == "tool":
            pending_tools.append({"type": "tool_result",
                                  "tool_use_id": msg.get("tool_call_id", ""),
                                  "content": msg.get("text", "")})
            continue
        flush_tools()
        if role == "user":
            block: Dict[str, Any] = {"role": "user",
                                     "content": [{"type": "text",
                                                  "text": msg.get("text", "")}]}
            # Defensive: merge accidental consecutive user turns.
            if converted and converted[-1]["role"] == "user":
                converted[-1]["content"].append(block["content"][0])
            else:
                converted.append(block)
        elif role == "assistant":
            content: List[Dict[str, Any]] = []
            if msg.get("text"):
                content.append({"type": "text", "text": msg["text"]})
            for call in msg.get("tool_calls") or []:
                content.append({"type": "tool_use",
                                "id": call.get("id", ""),
                                "name": call.get("name", ""),
                                "input": call.get("args", {})})
            converted.append({"role": "assistant", "content": content or
                              [{"type": "text", "text": ""}]})
    flush_tools()
    return {"model": cfg["model"], "max_tokens": max_tokens,
            "temperature": temperature,
            "system": "\n\n".join(system_parts) or "You are a Blender assistant.",
            "messages": converted, "tools": anthropic_tools(manifest)}


def parse_anthropic_response(data: Dict[str, Any]) -> Dict[str, Any]:
    blocks = data.get("content")
    if not isinstance(blocks, list):
        raise LlmError("BAD_RESPONSE", "Unrecognized Anthropic response.")
    texts, calls = [], []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            texts.append(block["text"])
        elif block.get("type") == "tool_use":
            calls.append({"id": block.get("id", f"call_{len(calls)}"),
                          "name": block.get("name", ""),
                          "args": block.get("input") or {}})
    return {"text": "\n".join(texts), "tool_calls": calls}


# ---------------------------------------------------------------------------
# Gemini native format
# ---------------------------------------------------------------------------

def build_gemini_payload(cfg: Dict[str, Any], messages: List[Dict[str, Any]],
                         manifest: List[Dict[str, Any]],
                         max_tokens: int = 2048,
                         temperature: float = 0.2) -> Dict[str, Any]:
    system_parts = [m.get("text", "") for m in messages if m.get("role") == "system"]
    contents: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []

    def flush_tools():
        if pending:
            contents.append({"role": "function", "parts": list(pending)})
            pending.clear()

    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue
        if role == "tool":
            pending.append({"functionResponse": {
                "name": msg.get("tool_name", ""),
                "response": {"result": msg.get("text", "")[:8000]}}})
            continue
        flush_tools()
        if role == "user":
            contents.append({"role": "user",
                             "parts": [{"text": msg.get("text", "")}]})
        elif role == "assistant":
            parts: List[Dict[str, Any]] = []
            if msg.get("text"):
                parts.append({"text": msg["text"]})
            for call in msg.get("tool_calls") or []:
                parts.append({"functionCall": {"name": call.get("name", ""),
                                               "args": call.get("args", {})}})
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
    flush_tools()
    return {"system_instruction": {"parts": [{"text": "\n\n".join(system_parts) or
                                              "You are a Blender assistant."}]},
            "contents": contents, "tools": gemini_tools(manifest),
            "generationConfig": {"temperature": temperature,
                                 "maxOutputTokens": max_tokens}}


def parse_gemini_response(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        raise LlmError("BAD_RESPONSE", "Unrecognized Gemini response.")
    texts, calls = [], []
    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        if "text" in part and part["text"]:
            texts.append(part["text"])
        if "functionCall" in part and isinstance(part["functionCall"], dict):
            func = part["functionCall"]
            calls.append({"id": f"call_{len(calls)}",
                          "name": func.get("name", ""),
                          "args": func.get("args") or {}})
    return {"text": "\n".join(texts), "tool_calls": calls}


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _post(url: str, headers: Dict[str, str], payload: Dict[str, Any],
          timeout: int) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
        except (OSError, ValueError):
            detail = ""
        if exc.code in (401, 403):
            raise LlmError("AUTH",
                           f"API key rejected ({exc.code}). Check the key. {detail}")
        if exc.code == 429:
            raise LlmError("RATE_LIMIT",
                           f"Rate limited / out of credit ({exc.code}). {detail}")
        if exc.code == 404:
            raise LlmError("NOT_FOUND",
                           f"Endpoint or model not found ({exc.code}). Check Endpoint/Model. {detail}")
        raise LlmError("HTTP_ERROR", f"Provider HTTP {exc.code}. {detail}")
    except urllib.error.URLError as exc:
        raise LlmError("NETWORK", f"Network error: {exc.reason}")
    except TimeoutError:
        raise LlmError("TIMEOUT", "Provider request timed out.")
    try:
        data = json.loads(raw)
    except ValueError:
        raise LlmError("BAD_RESPONSE", "Provider returned non-JSON.")
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise LlmError("PROVIDER_ERROR", message[:600])
    if not isinstance(data, dict):
        raise LlmError("BAD_RESPONSE", "Unrecognized provider response.")
    return data


def chat(cfg: Dict[str, Any], messages: List[Dict[str, Any]],
         manifest: List[Dict[str, Any]], max_tokens: int = 2048,
         temperature: float = 0.2, timeout: int = 120) -> Dict[str, Any]:
    """One chat round-trip. Returns {"text", "tool_calls"}. Raises LlmError."""
    fmt = cfg.get("format", "openai")
    base = cfg.get("base_url", "").rstrip("/")
    key = cfg.get("api_key", "")
    if fmt == "openai":
        url = f"{base}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        payload = build_openai_payload(cfg, messages, manifest, max_tokens, temperature)
        return parse_openai_response(_post(url, headers, payload, timeout))
    if fmt == "anthropic":
        url = f"{base}/v1/messages"
        headers = {"Content-Type": "application/json", "x-api-key": key,
                   "anthropic-version": "2023-06-01"}
        payload = build_anthropic_payload(cfg, messages, manifest, max_tokens, temperature)
        return parse_anthropic_response(_post(url, headers, payload, timeout))
    if fmt == "gemini":
        url = f"{base}/v1beta/models/{cfg.get('model')}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": key}
        payload = build_gemini_payload(cfg, messages, manifest, max_tokens, temperature)
        return parse_gemini_response(_post(url, headers, payload, timeout))
    raise LlmError("UNKNOWN_FORMAT", f"Unknown provider format '{fmt}'.")
