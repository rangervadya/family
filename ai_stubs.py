"""
AI stubs for Family Bot - теперь с реальной нейросетью!
Использует бесплатную модель Qwen 3.6 Plus через OpenRouter
"""

import logging
from ai_service import ai_service

logger = logging.getLogger(__name__)

async def generate_companion_reply(message: str, name: str = "друг", user_id: int = 0) -> str:
    """
    Генерация ответа компаньона через нейросеть
    
    Args:
        message: Текст сообщения пользователя
        name: Имя пользователя
        user_id: Telegram ID пользователя (для контекста)
    
    Returns:
        str: Ответ бота
    """
    try:
        # Используем реальный AI сервис с бесплатной моделью
        reply = await ai_service.generate_response(
            message=message,
            user_id=user_id,
            user_name=name
        )
        return reply
    except Exception as e:
        logger.error(f"AI generation failed in stub: {e}")
        return _fallback_reply(message, name)

def _fallback_reply(message: str, name: str) -> str:
    """
    Ответ-заглушка при недоступности AI (сохраняем работоспособность)
    """
    message_lower = message.lower()
    
    # Приветствия
    if any(word in message_lower for word in ['привет', 'здравствуй', 'доброе утро', 'добрый день', 'добрый вечер', 'здрасьте']):
        return (
            f"Здравствуйте, {name}! 🌷\n\n"
            f"Рада вас видеть! Как ваши дела?"
        )
    
    # Как дела
    if any(word in message_lower for word in ['как дела', 'как ты', 'дела как', 'как поживаешь', 'как настроение']):
        return (
            f"У меня всё отлично, {name}! 😊\n\n"
            f"Я здесь, чтобы помочь вам. Расскажите, что вас беспокоит?"
        )
    
    # Погода
    if any(word in message_lower for word in ['погод', 'прогноз', 'солнце', 'дождь', 'ветер', 'температура', 'градус']):
        return (
            f"🌤️ О погоде, {name}, лучше всего спросить через команду /weather\n\n"
            f"Так я смогу показать точный прогноз для вашего города!"
        )
    
    # Время
    if any(word in message_lower for word in ['время', 'часы', 'который час', 'дата', 'сегодня']):
        from datetime import datetime
        now = datetime.now()
        return (
            f"📅 Сегодня {now.strftime('%d.%m.%Y')}\n"
            f"🕐 Сейчас {now.strftime('%H:%M')}"
        )
    
    # Помощь
    if any(word in message_lower for word in ['помощь', 'help', 'что умеешь', 'команды', 'функции', 'возможности']):
        return (
            f"🤖 **Что я умею, {name}:**\n\n"
            f"• 🌤️ **Погода** — команда /weather\n"
            f"• 💊 **Напоминания** — /add_meds\n"
            f"• 💬 **Поговорить** — напишите что угодно\n"
            f"• 👨‍👩‍👧 **Семья** — кнопка в меню\n"
            f"• 🆘 **SOS** — экстренная помощь\n\n"
            f"Я здесь, чтобы поддержать вас! 🌷"
        )
    
    # Спасибо
    if any(word in message_lower for word in ['спасибо', 'благодарю', 'пасиб']):
        return (
            f"Пожалуйста, {name}! 😊\n\n"
            f"Всегда рада помочь. Обращайтесь, если что-то нужно!"
        )
    
    # Напоминания
    if any(word in message_lower for word in ['напомни', 'напоминание', 'лекарств', 'таблетк']):
        return (
            f"💊 Чтобы добавить напоминание о лекарствах, {name}, используйте команду /add_meds\n\n"
            f"Я буду каждый день напоминать вам в выбранное время!"
        )
    
    # Стандартный ответ для всего остального
    return (
        f"Спасибо за ваше сообщение, {name}! 😊\n\n"
        f"Я внимательно его прочитала. Если вам нужна помощь с напоминаниями, "
        f"прогнозом погоды или просто хочется поговорить — я всегда здесь!\n\n"
        f"Кстати, вы можете воспользоваться кнопками в меню для быстрого доступа к функциям."
    )

async def generate_fallback_reply(message: str, name: str = "друг") -> str:
    """
    Синхронная версия заглушки для обратной совместимости
    """
    return _fallback_reply(message, name)
