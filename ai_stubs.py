from __future__ import annotations

from typing import Optional

import httpx

from bot_config import get_settings

import logging

from ai_service import ai_service

logger = logging.getLogger(__name__)


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

    async def generate_companion_reply(message: str, name: str = "друг", user_id: int = 0) -> str:
    """Генерация ответа через реальную нейросеть (OpenRouter)"""
    try:
        reply = await ai_service.generate_response(message, user_name=name)
        return reply
    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        return f"Извините, {name}, что-то пошло не так. Попробуйте позже!"

