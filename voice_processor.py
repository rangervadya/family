import os
import logging
import io
import requests
import json

logger = logging.getLogger(__name__)

class VoiceProcessor:
    def __init__(self):
        self.available = True
        logger.info("✅ Voice processor ready (using direct Google Speech API)")

    async def process_voice(self, file_bytes: bytes, format: str = "ogg") -> str:
        logger.info(f"🎤 Processing {len(file_bytes)} bytes")
        
        try:
            # Конвертируем OGG в FLAC (Google Speech API лучше понимает FLAC)
            import subprocess
            import tempfile
            
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as ogg_file:
                ogg_file.write(file_bytes)
                ogg_path = ogg_file.name
            
            flac_path = ogg_path.replace('.ogg', '.flac')
            
            # Конвертируем через ffmpeg (если есть)
            try:
                subprocess.run(
                    ['ffmpeg', '-i', ogg_path, '-ac', '1', '-ar', '16000', flac_path],
                    check=True, capture_output=True
                )
                with open(flac_path, 'rb') as f:
                    flac_bytes = f.read()
            except:
                # Если ffmpeg нет, возвращаем None
                logger.error("ffmpeg not available")
                return None
            finally:
                os.unlink(ogg_path)
                if os.path.exists(flac_path):
                    os.unlink(flac_path)
            
            # Отправляем в Google Speech API (бесплатно, но с ограничениями)
            url = "https://www.google.com/speech-api/v2/recognize?output=json&lang=ru&key=AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"
            
            headers = {'Content-Type': 'audio/x-flac; rate=16000'}
            response = requests.post(url, headers=headers, data=flac_bytes)
            
            if response.status_code == 200:
                for line in response.text.strip().split('\n'):
                    try:
                        data = json.loads(line)
                        if 'result' in data and data['result']:
                            text = data['result'][0]['alternative'][0]['transcript']
                            logger.info(f"🎤 Recognized: {text}")
                            return text
                    except:
                        continue
            
            return None
            
        except Exception as e:
            logger.error(f"Voice processing error: {e}", exc_info=True)
            return None

voice_processor = VoiceProcessor()
