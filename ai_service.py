import os
import logging
import aiohttp
from storage import get_chat_history, save_message

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.model = "google/gemini-2.0-flash-exp:free"  # или openrouter/free
        self.available = bool(self.api_key)
        if self.available:
            logger.info(f"✅ AI Service ready. Model: {self.model}")
        else:
            logger.warning("⚠️ AI Service disabled: no OPENROUTER_API_KEY")

    async def generate_response(self, message: str, user_id: int, user_name: str = "друг") -> str:
        if not self.available:
            return self._fallback(message, user_name)

        # Получаем историю диалога (последние 10 сообщений, т.е. ~5 обменов)
        history = get_chat_history(user_id, limit=10)

        # Системный промпт
        system_prompt = (
            f"Ты — заботливый бот-компаньон «Семья». "
            f"Ты общаешься с {user_name}. Отвечай тепло, дружелюбно, кратко (2-3 предложения) на русском языке. "
            f"Учитывай предыдущий контекст разговора, если он есть."
        )

        # Формируем список сообщений для API
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)  # добавляем историю (user и assistant сообщения)
        messages.append({"role": "user", "content": message})  # текущее сообщение

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://family-bot-b4bd.onrender.com",
                        "X-Title": "Family Companion Bot"
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": 500,
                        "temperature": 0.7
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        reply = data["choices"][0]["message"]["content"]
                        # Сохраняем вопрос и ответ в историю
                        save_message(user_id, "user", message)
                        save_message(user_id, "assistant", reply)
                        return reply
                    else:
                        error_text = await response.text()
                        logger.error(f"AI API error {response.status}: {error_text}")
                        return self._fallback(message, user_name)
        except Exception as e:
            logger.error(f"AI request failed: {e}")
            return self._fallback(message, user_name)

    def _fallback(self, message: str, user_name: str) -> str:
        return f"Спасибо, {user_name}! 😊 Я сейчас учусь, но скоро отвечу на всё."

ai_service = AIService()
