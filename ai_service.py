import os
import logging
import aiohttp
import json

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        # Читаем API-ключ из переменных окружения
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        # Используем бесплатную и мощную модель
        self.model = os.environ.get("AI_MODEL", "qwen/qwen3.6-plus-preview:free")
        self.available = bool(self.api_key)
        
        if self.available:
            logger.info(f"✅ AI Service initialized with model: {self.model}")
        else:
            logger.warning("⚠️ AI Service disabled: OPENROUTER_API_KEY not set")

    async def generate_response(self, message: str, user_name: str = "друг") -> str:
        """Генерация ответа через OpenRouter"""
        if not self.available:
            return self._fallback(message, user_name)
        
        # Инструкция для нейросети, чтобы она вела себя как заботливый компаньон
        system_prompt = (
            f"Ты — заботливый бот-компаньон «Семья». "
            f"Ты общаешься с {user_name}. Отвечай тепло, дружелюбно, используй простые предложения. "
            f"Если тебя спрашивают о погоде, времени или других фактах — честно говори, что ты пока не знаешь, но порекомендуй использовать команды /weather или спросить время. "
            f"Отвечай на русском языке, кратко (2-3 предложения)."
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": message}
                        ],
                        "max_tokens": 300,
                        "temperature": 0.7
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data["choices"][0]["message"]["content"]
                    else:
                        error_text = await response.text()
                        logger.error(f"AI API error {response.status}: {error_text}")
                        return self._fallback(message, user_name)
        except Exception as e:
            logger.error(f"AI request failed: {e}")
            return self._fallback(message, user_name)
    
    def _fallback(self, message: str, user_name: str) -> str:
        """Простой ответ, если AI недоступен"""
        return f"Спасибо за сообщение, {user_name}! 😊 Я пока учусь отвечать на сложные вопросы, но обязательно отвечу позже."

# Создаем глобальный экземпляр сервиса
ai_service = AIService()
