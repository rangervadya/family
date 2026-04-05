import os
import logging
import aiohttp
import asyncio

logger = logging.getLogger(__name__)

class VoiceProcessor:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/audio/transcriptions"
        self.available = bool(self.api_key)

        if self.available:
            logger.info("✅ Voice processor ready (using OpenRouter)")

    async def process_voice(self, file_bytes: bytes, format: str = "ogg") -> str:
        if not self.available:
            logger.warning("Voice recognition not available")
            return None

        try:
            async with aiohttp.ClientSession() as session:
                form_data = aiohttp.FormData()
                form_data.add_field('file', file_bytes, filename='audio.ogg', content_type='audio/ogg')
                form_data.add_field('model', 'openai/whisper-large-v3-turbo')

                async with session.post(
                    self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        text = result.get("text", "")
                        if text:
                            logger.info(f"🎤 Recognized: {text[:50]}...")
                            return text
                    else:
                        error = await response.text()
                        logger.error(f"Whisper API error: {response.status} - {error}")
                        return None

        except Exception as e:
            logger.error(f"Voice processing error: {e}")
            return None

voice_processor = VoiceProcessor()
