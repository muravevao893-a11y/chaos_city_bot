from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class AiUnavailable(RuntimeError):
    pass


def _api_config() -> tuple[str, str, str, dict[str, str]] | None:
    settings = get_settings()
    provider = (settings.ai_provider or "openrouter").strip().lower()
    model = settings.ai_model.strip()
    if provider == "openai":
        key = settings.openai_api_key.strip()
        if not model:
            model = "gpt-4o-mini"
        if not key:
            return None
        return (
            "https://api.openai.com/v1/chat/completions",
            key,
            model,
            {},
        )
    key = settings.openrouter_api_key.strip()
    if not model:
        model = "openai/gpt-4o-mini"
    if not key:
        return None
    return (
        "https://openrouter.ai/api/v1/chat/completions",
        key,
        model,
        {
            "HTTP-Referer": settings.ai_site_url or "https://t.me/",
            "X-Title": settings.ai_app_name or "Chatograd",
        },
    )


def _system_prompt(kind: str) -> str:
    return (
        "Ты AI-ведущий русскоязычной Telegram-игры 'Чатоград'. "
        "Пиши коротко, живо, смешно, но без мата, травли, оскорблений по реальным признакам, политики и жести. "
        "Не придумывай реальные факты вне игровых данных. Не раскрывай приватные данные. "
        "Формат: 3-6 коротких строк, можно эмодзи. HTML/Markdown не используй. "
        f"Тип текста: {kind}."
    )


def _user_prompt(kind: str, payload: dict[str, Any]) -> str:
    city = payload.get("city", {})
    lines = [
        f"Город: {city.get('name', 'Чатоград')}",
        f"Ранг: {city.get('rank', 'Подъезд')}, уровень: {city.get('level', 1)}, казна: {city.get('treasury', 0)}, жители: {city.get('population', 0)}",
        f"Сила: {city.get('power', 0)}, режим: {payload.get('activity_mode', 'normal')}",
    ]
    if payload.get("top"):
        top = ", ".join(f"{item.get('name')} ({item.get('title')})" for item in payload["top"][:5])
        lines.append(f"Топ жителей: {top}")
    if payload.get("event"):
        event = payload["event"]
        lines.append(f"Активное событие: {event.get('title')} — {event.get('text')}")
    if payload.get("logs"):
        lines.append("Последние события:")
        lines.extend(f"- {item.get('text')}" for item in payload["logs"][:8])
    if payload.get("secret_hint"):
        lines.append(f"Секретный вайб: {payload['secret_hint']}")
    lines.append(f"Задача: напиши {kind} для чата по этим игровым фактам.")
    return "\n".join(lines)


async def generate_ai_text(kind: str, payload: dict[str, Any]) -> str | None:
    settings = get_settings()
    if not settings.ai_enabled:
        return None
    config = _api_config()
    if not config:
        logger.info("AI is enabled but API key/model config is missing")
        return None
    url, key, model, extra_headers = config
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        **extra_headers,
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _system_prompt(kind)},
            {"role": "user", "content": _user_prompt(kind, payload)},
        ],
        "temperature": 0.9,
        "max_tokens": max(80, min(int(settings.ai_max_tokens or 220), 600)),
    }
    try:
        async with httpx.AsyncClient(timeout=float(settings.ai_timeout_seconds or 10)) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        content = str(content).strip()
        if not content:
            return None
        # Keep Telegram messages compact and safe.
        content = content.replace("<", "‹").replace(">", "›")
        return content[:1200]
    except Exception:
        logger.exception("AI generation failed")
        return None
