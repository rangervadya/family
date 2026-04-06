import os
import re
import logging
import aiohttp
import io
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEATHER_KEY = os.environ.get("OPENWEATHER_API_KEY", "")

# Клавиатура
menu = ReplyKeyboardMarkup(
    [["💬 Поговорить", "📅 Напоминания"], ["👥 События", "🆘 ПОМОЩЬ"], ["👨‍👩‍👧 Семья", "⚙️ Настройки"]],
    resize_keyboard=True,
)

# Хранилище городов пользователей
user_city = {}

# ==================== ПОГОДА ====================

async def get_weather(city: str) -> str:
    if not WEATHER_KEY:
        return None
    
    city_map = {
        "москва": "Moscow", "санкт-петербург": "Saint Petersburg",
        "новосибирск": "Novosibirsk", "екатеринбург": "Yekaterinburg",
        "казань": "Kazan", "нижний новгород": "Nizhny Novgorod",
        "краснодар": "Krasnodar", "сочи": "Sochi"
    }
    
    city_en = city_map.get(city.lower(), city)
    
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city_en}&appid={WEATHER_KEY}&units=metric&lang=ru"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    temp = round(data['main']['temp'])
                    feels = round(data['main']['feels_like'])
                    humidity = data['main']['humidity']
                    wind = data['wind']['speed']
                    desc = data['weather'][0]['description']
                    name = data['name']
                    return (f"🌡️ **Погода в {name}**\n\n"
                           f"🌡️ Температура: **{temp}°C**\n"
                           f"🤔 Ощущается как: **{feels}°C**\n"
                           f"💧 Влажность: **{humidity}%**\n"
                           f"💨 Ветер: **{wind} м/с**\n"
                           f"📖 {desc.capitalize()}")
    except Exception as e:
        logger.error(f"Weather error: {e}")
    return None

# ==================== РАСПОЗНАВАНИЕ ГОЛОСА (БЕСПЛАТНО) ====================

def recognize_voice(audio_bytes: bytes) -> str:
    """Распознаёт голос через Google Speech Recognition (бесплатно)"""
    try:
        # Конвертируем OGG в WAV
        audio = AudioSegment.from_ogg(io.BytesIO(audio_bytes))
        audio = audio.set_channels(1).set_frame_rate(16000)
        
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        
        # Распознаём
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio_data = recognizer.record(source)
        
        # Пробуем русский
        try:
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            logger.info(f"Recognized (RU): {text}")
            return text.lower()
        except:
            pass
        
        # Пробуем английский
        try:
            text = recognizer.recognize_google(audio_data, language="en-US")
            logger.info(f"Recognized (EN): {text}")
            return text.lower()
        except:
            pass
        
        return None
    except Exception as e:
        logger.error(f"Voice recognition error: {e}")
        return None

# ==================== AI ОТВЕТ ====================

async def get_ai_response(message: str) -> str:
    return None  # AI отключён для простоты, можно включить позже

# ==================== ОБРАБОТЧИК ТЕКСТА ====================

async def start(update: Update, context):
    await update.message.reply_text("Здравствуйте! Я бот-компаньон «Семья» 🏡\n\nЧем могу помочь?", reply_markup=menu)

async def handle_text(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text and text[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️"]:
        text = text[1:].strip()
        if not text:
            await update.message.reply_text("Напишите что-нибудь!", reply_markup=menu)
            return
    
    text_lower = text.lower()
    
    # Погода
    if any(w in text_lower for w in ['погод', 'прогноз', 'дождь', 'ветер', 'температура']):
        city = user_city.get(user_id)
        if not city:
            await update.message.reply_text("🌤️ Скажите ваш город: «Я живу в Москве»", reply_markup=menu)
            return
        
        await update.message.reply_text("🌤️ Узнаю погоду...")
        weather = await get_weather(city)
        if weather:
            await update.message.reply_text(weather, parse_mode="Markdown", reply_markup=menu)
        else:
            await update.message.reply_text(f"😔 Не удалось найти погоду для {city}", reply_markup=menu)
        return
    
    # Время
    if any(w in text_lower for w in ['время', 'часы', 'который час', 'дата']):
        now = datetime.now()
        await update.message.reply_text(f"📅 {now.strftime('%d.%m.%Y')}\n🕐 {now.strftime('%H:%M')}", reply_markup=menu)
        return
    
    # Приветствие
    if any(w in text_lower for w in ['привет', 'здравствуй', 'доброе утро', 'добрый день']):
        await update.message.reply_text(f"Здравствуйте! 🌷\n\nЧем могу помочь?", reply_markup=menu)
        return
    
    # Установка города
    match = re.search(r'(живу в|я из|город)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', text_lower)
    if match:
        city = match.group(2).strip().capitalize()
        if len(city) > 1:
            user_city[user_id] = city
            await update.message.reply_text(f"✅ Запомнила! Ваш город: {city}\n\n🌤️ Теперь спрашивайте погоду!", reply_markup=menu)
            return
    
    # Стандартный ответ
    await update.message.reply_text(
        f"😊 Спасибо за сообщение!\n\n"
        f"Я могу:\n"
        f"• 🌤️ Показать погоду — скажите «погода»\n"
        f"• 🕐 Показать время — скажите «время»\n"
        f"• 🎤 Распознать голос — отправьте голосовое сообщение\n\n"
        f"А ещё я запоминаю ваш город! Скажите «Я живу в Москве»",
        reply_markup=menu
    )

# ==================== ОБРАБОТЧИК ГОЛОСА (С РАСПОЗНАВАНИЕМ) ====================

async def handle_voice(update: Update, context):
    user_id = update.effective_user.id
    processing = await update.message.reply_text("🎤 Распознаю голосовое сообщение...")
    
    try:
        # Скачиваем голосовое
        file = await context.bot.get_file(update.message.voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        
        # Распознаём (бесплатно, без ключа)
        recognized = await asyncio.get_event_loop().run_in_executor(
            None, recognize_voice, bytes(audio_bytes)
        )
        
        if not recognized:
            await processing.edit_text(
                "😔 Не удалось распознать голос.\n\n"
                "Попробуйте:\n"
                "• Говорить чётче\n"
                "• Уменьшить шум\n"
                "• Отправить сообщение короче (3-5 секунд)\n\n"
                "Или напишите текстом!",
                reply_markup=menu
            )
            return
        
        await processing.edit_text(f"📝 Вы сказали: {recognized}\n\n🤔 Обрабатываю...")
        
        # Проверяем команды
        # Погода
        if any(w in recognized for w in ['погод', 'прогноз', 'дождь', 'ветер', 'температура']):
            city = user_city.get(user_id)
            if not city:
                await processing.edit_text("🌤️ Сначала скажите ваш город: «Я живу в Москве»", reply_markup=menu)
                return
            
            weather = await get_weather(city)
            if weather:
                await processing.delete()
                await update.message.reply_text(weather, parse_mode="Markdown", reply_markup=menu)
            else:
                await processing.edit_text(f"😔 Не удалось найти погоду для {city}", reply_markup=menu)
            return
        
        # Время
        if any(w in recognized for w in ['время', 'часы', 'который час', 'дата']):
            now = datetime.now()
            await processing.delete()
            await update.message.reply_text(f"📅 {now.strftime('%d.%m.%Y')}\n🕐 {now.strftime('%H:%M')}", reply_markup=menu)
            return
        
        # Приветствие
        if any(w in recognized for w in ['привет', 'здравствуй', 'доброе утро', 'добрый день']):
            await processing.delete()
            await update.message.reply_text(f"Здравствуйте! 🌷\n\nЧем могу помочь?", reply_markup=menu)
            return
        
        # Установка города
        match = re.search(r'(живу в|я из|город)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', recognized)
        if match:
            city = match.group(2).strip().capitalize()
            if len(city) > 1:
                user_city[user_id] = city
                await processing.delete()
                await update.message.reply_text(f"✅ Запомнила! Ваш город: {city}\n\n🌤️ Теперь спрашивайте погоду!", reply_markup=menu)
                return
        
        # Если ничего не подошло
        await processing.edit_text(
            f"😊 Вы сказали: {recognized}\n\n"
            f"Я вас понял!\n\n"
            f"• Чтобы узнать погоду — скажите «погода»\n"
            f"• Чтобы узнать время — скажите «время»\n"
            f"• Чтобы я запомнил город — скажите «Я живу в Москве»",
            reply_markup=menu
        )
        
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await processing.edit_text("❌ Ошибка при обработке голоса. Попробуйте написать текстом.", reply_markup=menu)

# ==================== КОМАНДЫ ====================

async def help_cmd(update: Update, context):
    await update.message.reply_text(
        "🤖 **Команды:**\n\n"
        "• /start — начать\n"
        "• /help — помощь\n\n"
        "**Голосом можно:**\n"
        "• Сказать «погода» — покажет погоду\n"
        "• Сказать «время» — покажет время\n"
        "• Сказать «привет» — поздоровается\n"
        "• Сказать «я живу в Москве» — запомнит город\n\n"
        "**Текстом то же самое!**",
        parse_mode="Markdown", reply_markup=menu
    )

async def menu_cmd(update: Update, context):
    await update.message.reply_text("📋 Главное меню:", reply_markup=menu)

async def weather_cmd(update: Update, context):
    user_id = update.effective_user.id
    city = user_city.get(user_id)
    if not city:
        await update.message.reply_text("🌤️ Скажите ваш город: «Я живу в Москве»", reply_markup=menu)
        return
    
    await update.message.reply_text("🌤️ Узнаю погоду...")
    weather = await get_weather(city)
    if weather:
        await update.message.reply_text(weather, parse_mode="Markdown", reply_markup=menu)
    else:
        await update.message.reply_text(f"😔 Не удалось найти погоду для {city}", reply_markup=menu)

# ==================== ЗАПУСК ====================

def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("weather", weather_cmd))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("Bot started")
    app.run_polling(allowed_updates=["message", "voice"])

if __name__ == "__main__":
    main()
