import os
import json
import aiohttp
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.model = os.environ.get("AI_MODEL", "google/gemini-2.0-flash-exp:free")
        
    async def generate_response(
        self, 
        message: str, 
        user_id: int,
        context: Optional[List[Dict]] = None,
        user_name: str = "Пользователь"
    ) -> str:
        """Генерация ответа с учётом контекста и памяти"""
        
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not set, using fallback")
            return self._fallback_response(message)
        
        # Формируем системный промпт
        system_prompt = self._get_system_prompt(user_name)
        
        # Получаем релевантные факты из памяти
        memory_context = await self.get_user_memory(user_id, message)
        
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        
        if memory_context:
            messages.append({
                "role": "system", 
                "content": f"Информация о пользователе из памяти:\n{memory_context}"
            })
        
        if context:
            messages.extend(context)
        
        messages.append({"role": "user", "content": message})
        
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
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 500
                    }
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data["choices"][0]["message"]["content"]
                    else:
                        logger.error(f"AI API error: {response.status}")
                        return self._fallback_response(message)
        except Exception as e:
            logger.error(f"AI request failed: {e}")
            return self._fallback_response(message)
    
    def _get_system_prompt(self, user_name: str) -> str:
        return f"""Ты — заботливый бот-компаньон «Семья». Ты общаешься с пожилым человеком по имени {user_name}.

Твои правила:
1. Отвечай тепло, дружелюбно и заботливо
2. Используй простые, понятные предложения
3. Если нужно напомнить о здоровье — напомни
4. Интересуйся самочувствием пользователя
5. Не используй сложные технические термины
6. Будь терпеливым и понимающим

Твоя цель — поддерживать приятную беседу и помогать пользователю."""
    
    def _fallback_response(self, message: str) -> str:
        """Ответ-заглушка, если AI недоступен"""
        return f"Спасибо за сообщение! 😊\n\nЯ бы с радостью на него ответил, но сейчас у меня небольшие технические трудности с подключением к нейросети. Попробуйте написать чуть позже!"
    
    async def get_user_memory(self, user_id: int, query: str) -> str:
        """Получение релевантных фактов из памяти пользователя"""
        # Здесь будет RAG логика
        # Пока возвращаем заглушку
        return ""
    
    async def extract_facts(self, user_id: int, message: str, response: str) -> None:
        """Извлечение фактов о пользователе из диалога"""
        # Здесь будет автоматическое извлечение фактов
        pass

# Создаём глобальный экземпляр
ai_service = AIService()
