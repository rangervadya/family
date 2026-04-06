import os
import logging
import aiohttp
import json
import asyncio

logger = logging.getLogger(__name__)

class VoiceProcessor:
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/audio/transcriptions"
        self.available = bool(self.api_key)

        if self.available:
            logger.info("✅ Voice processor ready (using OpenRouter Whisper)")
            logger.info(f"   API Key: {self.api_key[:10]}...{self.api_key[-5:] if len(self.api_key) > 15 else ''}")
        else:
            logger.warning("⚠️ Voice processor disabled: OPENROUTER_API_KEY not set")

    async def process_voice(self, file_bytes: bytes, format: str = "ogg") -> str:
        if not self.available:
            logger.warning("Voice recognition not available")
            return None

        logger.info(f"🎤 process_voice called with {len(file_bytes)} bytes")
        
        # Сохраняем аудио для отладки (опционально, можно закомментировать)
        try:
            with open("/tmp/test_audio.ogg", "wb") as f:
                f.write(file_bytes)
            logger.info("🎤 Audio saved to /tmp/test_audio.ogg")
        except Exception as e:
            logger.warning(f"Could not save audio: {e}")
        
        try:
            async with aiohttp.ClientSession() as session:
                form_data = aiohttp.FormData()
                form_data.add_field('file', file_bytes, filename='audio.ogg', content_type='audio/ogg')
                form_data.add_field('model', 'openai/whisper-large-v3-turbo')
                
                logger.info("🎤 Sending request to OpenRouter Whisper API...")
                logger.info(f"🎤 URL: {self.base_url}")
                
                async with session.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    logger.info(f"🎤 Response status: {response.status}")
                    response_text = await response.text()
                    logger.info(f"🎤 Response body: {response_text[:500]}")
                    
                    if response.status == 200:
                        try:
                            result = json.loads(response_text)
                            text = result.get("text", "")
                            if text:
                                logger.info(f"🎤 ✅ Successfully recognized: '{text}'")
                                return text
                            else:
                                logger.warning("🎤 Empty response from Whisper")
                                return None
                        except json.JSONDecodeError as e:
                            logger.error(f"🎤 JSON decode error: {e}")
                            return None
                    else:
                        logger.error(f"🎤 Whisper API error: {response.status} - {response_text}")
                        return None

        except aiohttp.ClientError as e:
            logger.error(f"🎤 Network error: {e}")
            return None
        except asyncio.TimeoutError:
            logger.error("🎤 Request timeout")
            return None
        except Exception as e:
            logger.error(f"🎤 Voice processing error: {e}", exc_info=True)
            return None

voice_processor = VoiceProcessor()
