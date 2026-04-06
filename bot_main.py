import os
import re
import logging
import aiohttp
import io
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from pydub import AudioSegment
import speech_recognition as sr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
WEATHER_KEY = os.environ.get("OPENWEATHER_API_KEY", "")

# Клавиатура
menu = ReplyKeyboardMarkup(
    [["💬 Поговорить", "📅 Напоминания"], ["👥 События", "🆘 ПОМОЩЬ"], ["👨‍👩‍👧 Семья", "⚙️ Настройки"]],
    resize_keyboard=True,
)

# Хранилище городов и имён пользователей
user_data = {}

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

# ==================== AI ОТВЕТ ====================

async def get_ai_response(message: str, user_name: str = "") -> str:
    """Получение ответа от AI через OpenRouter"""
    if not OPENROUTER_KEY:
        return None
    
    system_prompt = f"Ты заботливый бот-компаньон «Семья». Отвечай тепло и дружелюбно. Пользователя зовут {user_name if user_name else 'друг'}. Отвечай на русском, кратко."
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "qwen/qwen3.6-plus-preview:free",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message}
                    ],
                    "max_tokens": 500,
                    "temperature": 0.7
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.error(f"AI API error: {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"AI error: {e}")
        return None

# ==================== РАСПОЗНАВАНИЕ ГОЛОСА ====================

def recognize_voice(audio_bytes: bytes) -> str:
    """Распознаёт голос через Google Speech Recognition"""
    try:
        audio = AudioSegment.from_ogg(io.BytesIO(audio_bytes))
        audio = audio.set_channels(1).set_frame_rate(16000)
        
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio_data = recognizer.record(source)
        
        try:
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            return text.lower()
        except:
            try:
                text = recognizer.recognize_google(audio_data, language="en-US")
                return text.lower()
            except:
                return None
    except Exception as e:
        logger.error(f"Voice recognition error: {e}")
        return None

# ==================== ОБРАБОТЧИК ТЕКСТА ====================

async def start(update: Update, context):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "Здравствуйте! Я бот-компаньон «Семья» 🏡\n\n"
        "Я помогу вам:\n"
        "• 💬 Поддержать разговор — просто напишите что угодно\n"
        "• 🌤️ Узнать погоду — скажите «погода»\n"
        "• 🕐 Узнать время — скажите «время»\n"
        "• 🎤 Отправить голосовое сообщение — я распознаю и отвечу\n\n"
        "Давайте познакомимся! Как вас зовут?",
        reply_markup=menu
    )

async def handle_text(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Убираем эмодзи меню
    if text and text[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️"]:
        text = text[1:].strip()
        if not text:
            await update.message.reply_text("Напишите что-нибудь, и мы поговорим! 😊", reply_markup=menu)
            return
    
    text_lower = text.lower()
    
    # Сохраняем имя пользователя
    if user_id not in user_data or not user_data[user_id].get("name"):
        if len(text) < 30 and not any(w in text_lower for w in ['погод', 'время', 'привет', 'здравствуй']):
            user_data[user_id] = user_data.get(user_id, {})
            user_data[user_id]["name"] = text
            await update.message.reply_text(
                f"Очень приятно, {text}! 🌷\n\n"
                f"Теперь я буду знать, как к вам обращаться.\n\n"
                f"Спрашивайте меня о чём угодно!",
                reply_markup=menu
            )
            return
    
    # Погода
    if any(w in text_lower for w in ['погод', 'прогноз', 'дождь', 'ветер', 'температура']):
        city = user_data.get(user_id, {}).get("city")
        if not city:
            await update.message.reply_text("🌤️ Скажите ваш город, например: «Я живу в Москве»", reply_markup=menu)
            return
        
        await update.message.reply_text("🌤️ Узнаю погоду...")
        weather = await get_weather(city)
        if weather:
            await update.message.reply_text(weather, parse_mode="Markdown", reply_markup=menu)
        else:
            await update.message.reply_text(f"😔 Не удалось найти погоду для {city}", reply_markup=menu)
        return
    
    # Время
    if any(w in text_lower for w in ['время', 'часы', 'который час', 'дата', 'сегодня']):
        now = datetime.now()
        await update.message.reply_text(f"📅 {now.strftime('%d.%m.%Y')}\n🕐 {now.strftime('%H:%M')}", reply_markup=menu)
        return
    
    # Приветствие
    if any(w in text_lower for w in ['привет', 'здравствуй', 'доброе утро', 'добрый день']):
        name = user_data.get(user_id, {}).get("name", "")
        await update.message.reply_text(f"Здравствуйте{f', {name}' if name else ''}! 🌷\n\nЧем могу помочь сегодня?", reply_markup=menu)
        return
    
    # Установка города
    match = re.search(r'(живу в|я из|город)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', text_lower)
    if match:
        city = match.group(2).strip().capitalize()
        if len(city) > 1:
            if user_id not in user_data:
                user_data[user_id] = {}
            user_data[user_id]["city"] = city
            await update.message.reply_text(f"✅ Запомнила! Ваш город: {city}\n\n🌤️ Теперь спрашивайте погоду!", reply_markup=menu)
            return
    
    # AI ответ
    thinking = await update.message.reply_text("🤔 Думаю над ответом...")
    name = user_data.get(user_id, {}).get("name", "")
    reply = await get_ai_response(text, name)
    
    if reply:
        await thinking.delete()
        await update.message.reply_text(reply, reply_markup=menu)
    else:
        await thinking.edit_text(
            f"😊 Спасибо за сообщение!\n\n"
            f"Я могу:\n"
            f"• 🌤️ Показать погоду — скажите «погода»\n"
            f"• 🕐 Показать время — скажите «время»\n"
            f"• 🎤 Отправить голосовое сообщение — я распознаю\n\n"
            f"А ещё я запоминаю ваш город и имя!",
            reply_markup=menu
        )

# ==================== ОБРАБОТЧИК ГОЛОСА ====================

async def handle_voice(update: Update, context):
    user_id = update.effective_user.id
    processing = await update.message.reply_text("🎤 Распознаю голосовое сообщение...")
    
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        
        recognized = await asyncio.get_event_loop().run_in_executor(
            None, recognize_voice, bytes(audio_bytes)
        )
        
        if not recognized:
            await processing.edit_text(
                "😔 Не удалось распознать голос.\n\n"
                "Попробуйте говорить чётче или напишите текстом!",
                reply_markup=menu
            )
            return
        
        await processing.edit_text(f"📝 Вы сказали: {recognized}\n\n🤔 Думаю над ответом...")
        
        # Проверяем команды
        if any(w in recognized for w in ['погод', 'прогноз', 'дождь', 'ветер', 'температура']):
            city = user_data.get(user_id, {}).get("city")
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
        
        if any(w in recognized for w in ['время', 'часы', 'который час', 'дата']):
            now = datetime.now()
            await processing.delete()
            await update.message.reply_text(f"📅 {now.strftime('%d.%m.%Y')}\n🕐 {now.strftime('%H:%M')}", reply_markup=menu)
            return
        
        if any(w in recognized for w in ['привет', 'здравствуй', 'доброе утро', 'добрый день']):
            name = user_data.get(user_id, {}).get("name", "")
            await processing.delete()
            await update.message.reply_text(f"Здравствуйте{f', {name}' if name else ''}! 🌷\n\nЧем могу помочь?", reply_markup=menu)
            return
        
        match = re.search(r'(живу в|я из|город)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', recognized)
        if match:
            city = match.group(2).strip().capitalize()
            if len(city) > 1:
                if user_id not in user_data:
                    user_data[user_id] = {}
                user_data[user_id]["city"] = city
                await processing.delete()
                await update.message.reply_text(f"✅ Запомнила! Ваш город: {city}\n\n🌤️ Теперь спрашивайте погоду!", reply_markup=menu)
                return
        
        # AI ответ на голос
        name = user_data.get(user_id, {}).get("name", "")
        reply = await get_ai_response(recognized, name)
        
        if reply:
            await processing.delete()
            await update.message.reply_text(reply, reply_markup=menu)
        else:
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
        "🤖 **Бот-компаньон «Семья»**\n\n"
        "**Что я умею:**\n"
        "• 💬 **Разговаривать** — просто напишите что угодно\n"
        "• 🌤️ **Погода** — скажите «погода»\n"
        "• 🕐 **Время** — скажите «время»\n"
        "• 🎤 **Голос** — отправьте голосовое сообщение\n"
        "• 🌆 **Город** — скажите «Я живу в Москве»\n"
        "• 👤 **Имя** — скажите «Меня зовут Анна»\n\n"
        "**Команды:**\n"
        "• /start — начать заново\n"
        "• /help — эта справка\n"
        "• /menu — показать меню",
        parse_mode="Markdown", reply_markup=menu
    )

async def menu_cmd(update: Update, context):
    await update.message.reply_text("📋 Главное меню:", reply_markup=menu)

async def weather_cmd(update: Update, context):
    user_id = update.effective_user.id
    city = user_data.get(user_id, {}).get("city")
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
    
    logger.info("Bot started with AI support")
    app.run_polling(allowed_updates=["message", "voice"])

if __name__ == "__main__":
    main()
