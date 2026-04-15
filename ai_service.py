import os
import logging
import aiohttp

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.model = "openrouter/free"
        self.available = bool(self.api_key)

        if self.available:
            logger.info(f"✅ AI Service ready. Model: {self.model}")
        else:
            logger.warning("⚠️ AI Service disabled: no OPENROUTER_API_KEY")

    async def generate_response(self, message: str, user_id: int, user_name: str = "друг") -> str:
        if not self.available:
            return self._fallback(message, user_name)

        system_prompt = (
            f"Ты — заботливый бот-компаньон «Семья». "
            f"Ты общаешься с {user_name}. Отвечай тепло, дружелюбно, кратко (2-3 предложения) на русском языке."
        )

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
        return f"Спасибо, {user_name}! 😊 Я сейчас учусь, но скоро отвечу на всё."

ai_service = AIService()
