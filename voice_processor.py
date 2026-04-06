import os
import logging
import aiohttp
import json

logger = logging.getLogger(__name__)

class VoiceProcessor:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/audio/transcriptions"
        self.available = bool(self.api_key)

        if self.available:
            logger.info("✅ Voice processor ready (using OpenRouter Whisper)")
        else:
            logger.warning("⚠️ Voice processor disabled: OPENROUTER_API_KEY not set")

    async def process_voice(self, file_bytes: bytes, format: str = "ogg") -> str:
        if not self.available:
            logger.warning("Voice recognition not available")
            return None

        logger.info(f"🎤 process_voice called with {len(file_bytes)} bytes")
        
        try:
            async with aiohttp.ClientSession() as session:
                form_data = aiohttp.FormData()
                form_data.add_field('file', file_bytes, filename='audio.ogg', content_type='audio/ogg')
                form_data.add_field('model', 'openai/whisper-large-v3-turbo')
                
                logger.info("🎤 Sending request to OpenRouter Whisper API...")
                
                async with session.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    response_text = await response.text()
                    logger.info(f"🎤 Response status: {response.status}")
                    
                    if response.status == 200:
                        result = json.loads(response_text)
                        text = result.get("text", "")
                        if text:
                            logger.info(f"🎤 Successfully recognized: {text[:100]}")
                            return text
                        else:
                            logger.warning("Empty response from Whisper")
                            return None
                    else:
                        logger.error(f"Whisper API error: {response.status} - {response_text}")
                        return None

        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            return None
        except Exception as e:
            logger.error(f"Voice processing error: {e}", exc_info=True)
            return None

voice_processor = VoiceProcessor()
