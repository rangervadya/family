import os
import logging
import aiohttp
import json

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        # Используем универсальный роутер для бесплатных моделей
        self.model = os.environ.get("AI_MODEL", "openrouter/free")
        self.available = bool(self.api_key)
        
        if self.available:
            logger.info(f"✅ AI Service initialized with model: {self.model}")
        else:
            logger.warning("⚠️ AI Service disabled: OPENROUTER_API_KEY not set")

    async def generate_response(self, message: str, user_name: str = "друг") -> str:
        if not self.available:
            return self._fallback(message, user_name)
        
        system_prompt = (
            f"Ты — заботливый бот-компаньон «Семья». "
            f"Ты общаешься с {user_name}. Отвечай тепло, дружелюбно, используй простые предложения. "
            f"Отвечай на русском языке, кратко (2-3 предложения)."
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://family-bot-b4bd.onrender.com",  # Замените на ваш URL
                        "X-Title": "Family Companion Bot"
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
        return f"Спасибо за сообщение, {user_name}! 😊 Я пока учусь отвечать на сложные вопросы, но обязательно отвечу позже."

ai_service = AIService()
