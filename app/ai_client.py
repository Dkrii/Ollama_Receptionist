import json
from typing import Iterator

import requests

from config import settings


_http_session = requests.Session()


def _provider() -> str:
    provider = str(getattr(settings, "ai_provider", "ollama") or "ollama").strip().lower()
    return provider if provider in {"ollama", "openrouter"} else "ollama"


def _openrouter_headers() -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if settings.openrouter_site_url:
        headers["HTTP-Referer"] = settings.openrouter_site_url
    if settings.openrouter_site_name:
        headers["X-Title"] = settings.openrouter_site_name
    return headers


def _resolve_chat_model() -> str:
    if _provider() == "openrouter":
        return settings.openrouter_chat_model or settings.ollama_chat_model
    return settings.ollama_chat_model


def _resolve_embed_model() -> str:
    if _provider() == "openrouter":
        return settings.openrouter_embed_model or settings.ollama_embed_model
    return settings.ollama_embed_model


def _openrouter_base() -> str:
    return settings.openrouter_base_url.rstrip("/")


def generate_text(
    *,
    prompt: str,
    system: str = "",
    stream: bool = False,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int = 120,
) -> dict:
    if _provider() == "openrouter":
        messages: list[dict[str, str]] = []
        if system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict = {
            "model": _resolve_chat_model(),
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if isinstance(max_tokens, int) and max_tokens > 0:
            payload["max_tokens"] = max_tokens

        if not stream:
            response = _http_session.post(
                f"{_openrouter_base()}/chat/completions",
                headers=_openrouter_headers(),
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            body = response.json() or {}
            choices = body.get("choices") or []
            first_choice = choices[0] if choices else {}
            message = first_choice.get("message") or {}
            content = str(message.get("content") or "")
            finish_reason = str(first_choice.get("finish_reason") or "")
            return {
                "response": content,
                "done_reason": finish_reason,
            }

        return {
            "stream": stream_text_tokens(
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        }

    options = {
        "temperature": temperature,
        "num_ctx": settings.ollama_num_ctx,
    }
    if isinstance(max_tokens, int) and max_tokens > 0:
        options["num_predict"] = max_tokens
    if settings.ollama_num_thread > 0:
        options["num_thread"] = settings.ollama_num_thread

    response = _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": _resolve_chat_model(),
            "prompt": prompt,
            "system": system,
            "stream": stream,
            "options": options,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json() or {}


def stream_text_tokens(
    *,
    prompt: str,
    system: str = "",
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: int = 120,
) -> Iterator[str]:
    if _provider() == "openrouter":
        messages: list[dict[str, str]] = []
        if system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict = {
            "model": _resolve_chat_model(),
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if isinstance(max_tokens, int) and max_tokens > 0:
            payload["max_tokens"] = max_tokens

        with _http_session.post(
            f"{_openrouter_base()}/chat/completions",
            headers=_openrouter_headers(),
            json=payload,
            stream=True,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue

                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    if raw == "[DONE]":
                        break
                    continue

                chunk = json.loads(raw)
                choices = chunk.get("choices") or []
                first_choice = choices[0] if choices else {}
                delta = first_choice.get("delta") or {}
                token = delta.get("content")
                if token:
                    yield str(token)
        return

    options = {
        "temperature": temperature,
        "num_ctx": settings.ollama_num_ctx,
    }
    if isinstance(max_tokens, int) and max_tokens > 0:
        options["num_predict"] = max_tokens
    if settings.ollama_num_thread > 0:
        options["num_thread"] = settings.ollama_num_thread

    with _http_session.post(
        f"{settings.ollama_base_url}/api/generate",
        json={
            "model": _resolve_chat_model(),
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": options,
        },
        stream=True,
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            chunk = requests.models.complexjson.loads(line)
            token = chunk.get("response", "")
            if token:
                yield token
            if chunk.get("done"):
                break


def embed_text(text: str, timeout: int = 90) -> list[float]:
    value = (text or "").strip()
    if _provider() == "openrouter":
        response = _http_session.post(
            f"{_openrouter_base()}/embeddings",
            headers=_openrouter_headers(),
            json={
                "model": _resolve_embed_model(),
                "input": value,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json() or {}
        data = payload.get("data") or []
        if not data:
            return []
        embedding = (data[0] or {}).get("embedding") or []
        return [float(item) for item in embedding]

    response = _http_session.post(
        f"{settings.ollama_base_url}/api/embeddings",
        json={
            "model": _resolve_embed_model(),
            "prompt": value,
            "keep_alive": "30m",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    embedding = response.json().get("embedding") or []
    return [float(item) for item in embedding]


def provider_health() -> dict[str, str | int]:
    if _provider() == "openrouter":
        response = _http_session.get(
            f"{_openrouter_base()}/models",
            headers=_openrouter_headers(),
            timeout=8,
        )
        response.raise_for_status()
        models = (response.json() or {}).get("data") or []
        return {
            "provider": "openrouter",
            "model_count": len(models),
            "label": "OpenRouter",
        }

    response = _http_session.get(f"{settings.ollama_base_url}/api/tags", timeout=5)
    response.raise_for_status()
    models = (response.json() or {}).get("models") or []
    return {
        "provider": "ollama",
        "model_count": len(models),
        "label": "Ollama",
    }
