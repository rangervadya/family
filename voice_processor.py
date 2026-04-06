import os
import logging
import io
import speech_recognition as sr
from pydub import AudioSegment

logger = logging.getLogger(__name__)

class VoiceProcessor:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.available = True
        logger.info("✅ Voice processor ready (Google Speech Recognition - FREE)")

    async def process_voice(self, file_bytes: bytes, format: str = "ogg") -> str:
        logger.info(f"🎤 Processing voice message: {len(file_bytes)} bytes")
        
        try:
            # Конвертируем OGG в WAV
            audio = AudioSegment.from_ogg(io.BytesIO(file_bytes))
            
            # Конвертируем в нужный формат (моно, 16kHz)
            audio = audio.set_channels(1).set_frame_rate(16000)
            
            # Экспортируем в WAV
            wav_io = io.BytesIO()
            audio.export(wav_io, format="wav")
            wav_io.seek(0)
            
            # Распознаём через Google Speech Recognition
            with sr.AudioFile(wav_io) as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio_data = self.recognizer.record(source)
            
            # Пробуем распознать русскую речь
            try:
                text = self.recognizer.recognize_google(audio_data, language="ru-RU")
                logger.info(f"🎤 Recognized (RU): {text}")
                return text
            except sr.UnknownValueError:
                logger.warning("Could not recognize Russian speech")
            
            # Пробуем английский
            try:
                text = self.recognizer.recognize_google(audio_data, language="en-US")
                logger.info(f"🎤 Recognized (EN): {text}")
                return text
            except sr.UnknownValueError:
                logger.warning("Could not recognize English speech")
            
            return None
            
        except Exception as e:
            logger.error(f"Voice processing error: {e}", exc_info=True)
            return None

voice_processor = VoiceProcessor()
