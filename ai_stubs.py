"""
AI stubs for Family Bot - теперь с реальной нейросетью!
Использует OpenRouter для генерации ответов.
"""

import logging
from ai_service import ai_service

logger = logging.getLogger(__name__)

async def generate_companion_reply(message: str, name: str = "друг", user_id: int = 0) -> str:
    """
    Генерация ответа через реальную нейросеть.

    Args:
        message: Текст сообщения пользователя
        name: Имя пользователя
        user_id: Telegram ID (пока не используется, но можно для контекста)

    Returns:
        str: Ответ бота
    """
    try:
        # Используем AI сервис из файла ai_service.py
        reply = await ai_service.generate_response(message, user_name=name)
        return reply
    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        return f"Извините, {name}, что-то пошло не так. Попробуйте позже!"
