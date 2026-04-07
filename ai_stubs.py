from __future__ import annotations

from typing import Optional

import httpx

from bot_config import get_settings


async def generate_companion_reply(user_text: str, name: str | None = None) -> str:
    """Асинхронная заглушка для AI-компаньона.

    Если Deepseek не настроен в окружении, возвращаем простой эмпатичный ответ.
    Если настроен — пробуем сделать HTTP-запрос к API (формат запроса зависит от конкретного провайдера,
    поэтому здесь остаётся упрощённый пример).
    """
    settings = get_settings()
    if not settings.deepseek_api_url or not settings.deepseek_api_key:
        prefix = f"{name}, " if name else ""
        return (
            f"{prefix}я вас внимательно слушаю. 🌷\n\n"
            "Сейчас у меня включён простой режим без настоящего искусственного интеллекта.\n"
            "Но я всё равно постараюсь поддержать вас. Расскажите, что у вас на душе?"
        )

    prompt = (
        "Ты добрый, терпеливый собеседник для пожилого человека.\n"
        "Отвечай простым, тёплым языком, без сложных терминов.\n"
        "Поддерживай, задавай мягкие уточняющие вопросы.\n\n"
        f"Сообщение пользователя: {user_text}"
    )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # Примерный формат; его нужно будет адаптировать под реальный Deepseek API
            response = await client.post(
                settings.deepseek_api_url,
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                json={"prompt": prompt, "max_tokens": 256},
            )
        response.raise_for_status()
        data = response.json()
        text: Optional[str] = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        ) or data.get("text")
        if not text:
            raise ValueError("empty response from AI")
        return text.strip()
    except Exception:
        prefix = f"{name}, " if name else ""
        return (
            f"{prefix}кажется, у нас временные трудности со связью с умным помощником.\n"
            "Но я рядом и готова просто поговорить с вами. ❤️"
        )

