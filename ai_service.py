import os
import json
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

class AIService:
    """Сервис для работы с AI через OpenRouter (бесплатная модель Qwen 3.6 Plus)"""
    
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        # 🔥 ИСПОЛЬЗУЕМ БЕСПЛАТНУЮ МОДЕЛЬ Qwen 3.6 Plus Preview
        self.model = "qwen/qwen3.6-plus-preview:free"
        self.available = bool(self.api_key)
        
        if self.available:
            logger.info(f"✅ AI Service initialized with FREE model: {self.model}")
            logger.info(f"   - No daily limits!")
            logger.info(f"   - 1 million token context!")
        else:
            logger.warning("⚠️ AI Service disabled: OPENROUTER_API_KEY not set")
    
    async def generate_response(
        self, 
        message: str, 
        user_id: int = 0,
        user_name: str = "Пользователь",
        context: Optional[List[Dict]] = None
    ) -> str:
        """Генерация ответа через бесплатную модель Qwen 3.6 Plus"""
        
        if not self.available:
            return self._fallback_response(message, user_name)
        
        # Формируем системный промпт
        system_prompt = self._get_system_prompt(user_name)
        
        # Собираем сообщения для API
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Добавляем контекст диалога (если есть)
        if context:
            messages.extend(context[-10:])  # Последние 10 сообщений для контекста
        
        # Добавляем текущее сообщение пользователя
        messages.append({"role": "user", "content": message})
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://family-bot.onrender.com",
                        "X-Title": "Family Companion Bot"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 500,
                        "top_p": 0.9,
                        "frequency_penalty": 0.5,
                        "presence_penalty": 0.5
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = data["choices"][0]["message"]["content"]
                        logger.info(f"AI response generated successfully")
                        return result
                    else:
                        error_text = await response.text()
                        logger.error(f"AI API error {response.status}: {error_text}")
                        return self._fallback_response(message, user_name)
        except Exception as e:
            logger.error(f"AI request failed: {e}")
            return self._fallback_response(message, user_name)
    
    def _get_system_prompt(self, user_name: str) -> str:
        """Системный промпт для бота-компаньона"""
        return f"""Ты — заботливый бот-компаньон «Семья». Ты общаешься с {user_name}.

Твои правила общения:
1. Отвечай тепло, дружелюбно и заботливо
2. Используй простые, понятные предложения (как для пожилого человека)
3. Интересуйся самочувствием пользователя
4. Если пользователь пишет о проблемах со здоровьем — прояви сочувствие и посоветуй обратиться к врачу
5. Не используй сложные технические термины
6. Будь терпеливым и понимающим
7. Если не знаешь ответа — честно скажи об этом
8. Поддерживай позитивный настрой

Твоя цель — быть добрым собеседником и помогать {user_name} чувствовать себя лучше.

Отвечай на русском языке, кратко и по существу."""
    
    def _fallback_response(self, message: str, user_name: str) -> str:
        """Ответ-заглушка при недоступности AI (сохраняем функциональность)"""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ['привет', 'здравствуй', 'добрый день']):
            return f"Здравствуйте, {user_name}! 🌷 Рада вас видеть! Как ваши дела?"
        
        if any(word in message_lower for word in ['как дела', 'как ты', 'дела как', 'как поживаешь']):
            return f"У меня всё отлично, {user_name}! 😊 Я каждый день учусь новому, чтобы лучше вам помогать. А как вы себя чувствуете сегодня?"
        
        if any(word in message_lower for word in ['спасибо', 'благодарю']):
            return f"Пожалуйста, {user_name}! 😊 Всегда рада помочь. Обращайтесь, если что-то нужно!"
        
        if any(word in message_lower for word in ['пока', 'до свидания']):
            return f"До свидания, {user_name}! 🌷 Хорошего дня! Я всегда здесь, если захотите поговорить."
        
        if any(word in message_lower for word in ['помощь', 'help', 'что умеешь']):
            return (
                f"Вот что я умею, {user_name}! 🤖\n\n"
                f"• 💬 Просто поговорить — напишите мне что угодно\n"
                f"• 📅 Напоминания — добавьте через /add_meds\n"
                f"• 🌤️ Погода — команда /weather\n"
                f"• 👨‍👩‍👧 Семья — кнопка в меню\n"
                f"• 🆘 SOS — экстренная помощь\n\n"
                f"А ещё я умею запоминать важную информацию о вас!"
            )
        
        # Стандартный ответ
        return (
            f"Спасибо за ваше сообщение, {user_name}! 😊\n\n"
            f"Я внимательно его прочитала. Если вам нужна помощь с напоминаниями, "
            f"прогнозом погоды или просто хочется поговорить — я всегда здесь!\n\n"
            f"Кстати, вы можете воспользоваться кнопками в меню для быстрого доступа к функциям.\n\n"
            f"Расскажите, как прошёл ваш день?"
        )
    
    async def get_user_memory(self, user_id: int) -> str:
        """Получение сохранённой информации о пользователе из БД"""
        try:
            import sqlite3
            conn = sqlite3.connect('family_bot.db')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, age, city, interests FROM users WHERE telegram_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            conn.close()
            
            if row and any(row):
                facts = []
                if row[0]: facts.append(f"Имя: {row[0]}")
                if row[1]: facts.append(f"Возраст: {row[1]}")
                if row[2]: facts.append(f"Город: {row[2]}")
                if row[3]: facts.append(f"Интересы: {row[3]}")
                return "\n".join(facts)
        except Exception as e:
            logger.error(f"Memory error: {e}")
        return ""

# Создаём глобальный экземпляр для использования во всём боте
ai_service = AIService()
