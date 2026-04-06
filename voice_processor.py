import os
import logging
import aiohttp
import json

logger = logging.getLogger(__name__)

class VoiceProcessor:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.available = bool(self.api_key)
        
        if self.available:
            logger.info("✅ Voice processor ready (OpenRouter Whisper)")
        else:
            logger.warning("⚠️ Voice processor disabled. Add OPENROUTER_API_KEY")

    async def process_voice(self, file_bytes: bytes, format: str = "ogg") -> str:
        if not self.available:
            return None

        logger.info(f"Processing {len(file_bytes)} bytes")
        
        try:
            async with aiohttp.ClientSession() as session:
                form_data = aiohttp.FormData()
                form_data.add_field('file', file_bytes, filename='audio.ogg', content_type='audio/ogg')
                form_data.add_field('model', 'openai/whisper-large-v3-turbo')
                
                async with session.post(
                    "https://openrouter.ai/api/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        text = result.get("text", "")
                        if text:
                            logger.info(f"Recognized: {text[:50]}")
                            return text
                    else:
                        logger.error(f"Whisper API error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Voice error: {e}")
            return None

voice_processor = VoiceProcessor()
