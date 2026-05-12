from __future__ import annotations

import json
import re
from typing import Any


def _is_deepseek(base_url: str | None, model_name: str | None) -> bool:
    haystack = f"{base_url or ''} {model_name or ''}".lower()
    return "deepseek" in haystack


def create_chat_completion(
    *,
    client,
    base_url: str | None,
    model_name: str | None,
    messages: list[dict[str, str]],
    temperature: float = 0.3,
    timeout: float = 60.0,
    extra_body: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "timeout": timeout,
    }
    if _is_deepseek(base_url, model_name):
        payload["extra_body"] = extra_body or {"thinking": {"type": "disabled"}}
    elif extra_body is not None:
        payload["extra_body"] = extra_body
    payload.update(kwargs)
    return client.chat.completions.create(**payload)


def extract_message_text(response: Any) -> str:
    return ((response.choices[0].message.content if response and response.choices else "") or "").strip()


def strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def parse_json_text(raw: str) -> Any:
    return json.loads(strip_json_fence(raw))


# ── Unified call helpers ──

def _extract_llm_params(provider: Any) -> dict[str, Any]:
    skill = getattr(provider, "llm_skill", None)
    if skill is not None:
        return {
            "client": getattr(skill, "client", None),
            "base_url": getattr(skill, "base_url", ""),
            "model_name": getattr(skill, "model_name", ""),
        }
    if hasattr(provider, "_client") or hasattr(provider, "_backend"):
        backend = getattr(provider, "_backend", provider)
        skill = getattr(backend, "llm_skill", None) if backend is not provider else None
        if skill is not None:
            return {
                "client": getattr(skill, "client", None),
                "base_url": getattr(skill, "base_url", ""),
                "model_name": getattr(skill, "model_name", ""),
            }
    return {
        "client": getattr(provider, "client", None),
        "base_url": getattr(provider, "base_url", ""),
        "model_name": getattr(provider, "model_name", ""),
    }


def call_llm(
    provider: Any,
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.3,
    timeout: float = 60.0,
    extra_body: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    params = _extract_llm_params(provider)
    client = params["client"]
    if client is None:
        raise RuntimeError("LLM client is not configured")
    return create_chat_completion(
        client=client,
        base_url=params["base_url"],
        model_name=model or params["model_name"],
        messages=messages,
        temperature=temperature,
        timeout=timeout,
        extra_body=extra_body,
        **kwargs,
    )


def call_llm_text(
    provider: Any,
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.3,
    timeout: float = 60.0,
    extra_body: dict[str, Any] | None = None,
    **kwargs: Any,
) -> str:
    response = call_llm(
        provider,
        messages=messages,
        model=model,
        temperature=temperature,
        timeout=timeout,
        extra_body=extra_body,
        **kwargs,
    )
    return extract_message_text(response)


def call_llm_json(
    provider: Any,
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.3,
    timeout: float = 60.0,
    extra_body: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Any:
    raw = call_llm_text(
        provider,
        messages=messages,
        model=model,
        temperature=temperature,
        timeout=timeout,
        extra_body=extra_body,
        **kwargs,
    )
    return parse_json_text(raw)
