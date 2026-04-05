import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Попытка импортировать AI сервис
try:
    from ai_service import ai_service
    AI_AVAILABLE = bool(os.environ.get("OPENROUTER_API_KEY"))
except ImportError:
    AI_AVAILABLE = False
    logger.warning("AI service not available")

async def generate_companion_reply(message: str, name: str = "друг", user_id: int = 0) -> str:
    """Генерация ответа компаньона через AI"""
    
    # Если AI доступен — используем его
    if AI_AVAILABLE:
        try:
            return await ai_service.generate_response(
                message=message,
                user_id=user_id,
                user_name=name
            )
        except Exception as e:
            logger.error(f"AI generation failed: {e}")
            return _fallback_reply(message, name)
    
    # Иначе используем заглушку
    return _fallback_reply(message, name)

def _fallback_reply(message: str, name: str) -> str:
    """Ответ-заглушка для MVP"""
    message_lower = message.lower()
    
    if any(word in message_lower for word in ['привет', 'здравствуй', 'добрый день']):
        return f"Здравствуйте, {name}! 🌷 Рада вас видеть! Как ваши дела?"
    
    if any(word in message_lower for word in ['как дела', 'как ты', 'дела как']):
        return f"У меня всё отлично, {name}! Я учусь новому каждый день, чтобы лучше вам помогать. А как вы себя чувствуете?"
    
    if any(word in message_lower for word in ['спасибо', 'благодарю']):
        return f"Пожалуйста, {name}! 😊 Всегда рада помочь. Обращайтесь, если что-то нужно!"
    
    if any(word in message_lower for word in ['погод', 'солнце', 'дождь']):
        return f"О погоде, {name}, лучше всего спросить в команде /weather — я покажу точный прогноз для вашего города!"
    
    # Стандартный ответ
    return (
        f"Спасибо за ваше сообщение, {name}! 😊\n\n"
        f"Я внимательно его прочитала. Если вам нужна помощь с напоминаниями, "
        f"прогнозом погоды или просто хочется поговорить — я всегда здесь!\n\n"
        f"Кстати, вы можете воспользоваться кнопками в меню для быстрого доступа к функциям."
    )
