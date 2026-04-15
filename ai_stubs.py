import logging
from ai_service import ai_service

logger = logging.getLogger(__name__)

async def generate_companion_reply(message: str, name: str = "друг", user_id: int = 0) -> str:
    try:
        # Передаём все три аргумента: message, user_id, user_name
        reply = await ai_service.generate_response(message, user_id, user_name=name)
        return reply
    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        return f"Извините, {name}, что-то пошло не так. Попробуйте позже!"
