import io
import logging
import aiohttp
import asyncio
from pydub import AudioSegment
import speech_recognition as sr

logger = logging.getLogger(__name__)

class VoiceProcessor:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        # OpenAI Whisper API (опционально, если есть ключ)
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        
    async def process_voice(self, file_bytes: bytes, format: str = "ogg") -> str:
        """Обработка голосового сообщения и распознавание текста"""
        
        try:
            # Конвертируем OGG в WAV для распознавания
            wav_bytes = await self.convert_ogg_to_wav(file_bytes)
            
            # Сохраняем временно в память
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio = self.recognizer.record(source)
            
            # Пробуем распознать русскую речь
            try:
                text = self.recognizer.recognize_google(audio, language="ru-RU")
                logger.info(f"Voice recognized (Google): {text}")
                return text
            except sr.UnknownValueError:
                logger.warning("Google Speech Recognition could not understand audio")
                
            # Пробуем английский, если русский не распознался
            try:
                text = self.recognizer.recognize_google(audio, language="en-US")
                logger.info(f"Voice recognized (Google EN): {text}")
                return text
            except sr.UnknownValueError:
                pass
                
            # Если есть OpenAI API, пробуем Whisper
            if self.openai_api_key:
                text = await self.whisper_transcribe(file_bytes)
                if text:
                    return text
            
            return None
            
        except Exception as e:
            logger.error(f"Voice processing error: {e}")
            return None
    
    async def convert_ogg_to_wav(self, ogg_bytes: bytes) -> bytes:
        """Конвертация OGG в WAV"""
        try:
            # Загружаем OGG из памяти
            audio = AudioSegment.from_ogg(io.BytesIO(ogg_bytes))
            
            # Конвертируем в WAV
            wav_io = io.BytesIO()
            audio.export(wav_io, format="wav")
            return wav_io.getvalue()
        except Exception as e:
            logger.error(f"Conversion error: {e}")
            return ogg_bytes
    
    async def whisper_transcribe(self, audio_bytes: bytes) -> str:
        """Распознавание через OpenAI Whisper API"""
        if not self.openai_api_key:
            return None
        
        try:
            async with aiohttp.ClientSession() as session:
                # Подготавливаем файл для отправки
                form_data = aiohttp.FormData()
                form_data.add_field('file', audio_bytes, filename='audio.ogg', content_type='audio/ogg')
                form_data.add_field('model', 'whisper-1')
                form_data.add_field('language', 'ru')
                
                async with session.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.openai_api_key}"},
                    data=form_data
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("text", "")
        except Exception as e:
            logger.error(f"Whisper error: {e}")
        
        return None

voice_processor = VoiceProcessor()
