import os
import re
import logging
import aiohttp
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

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

# ==================== AI ОТВЕТ ====================

async def get_ai_response(message: str) -> str:
    if not OPENROUTER_KEY:
        return "AI временно недоступен."
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                json={"model": "qwen/qwen3.6-plus-preview:free", "messages": [{"role": "user", "content": message}], "max_tokens": 300},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    return "Ошибка API. Попробуйте позже."
    except Exception as e:
        logger.error(f"AI error: {e}")
        return "Ошибка. Попробуйте ещё раз."

# ==================== ОБРАБОТЧИК ТЕКСТА ====================

async def start(update: Update, context):
    await update.message.reply_text("Здравствуйте! Я бот-компаньон «Семья» 🏡\n\nЧем могу помочь?", reply_markup=menu)

async def handle_text(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Убираем эмодзи меню
    if text and text[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️"]:
        text = text[1:].strip()
        if not text:
            await update.message.reply_text("Напишите что-нибудь!", reply_markup=menu)
            return
    
    text_lower = text.lower()
    
    # Погода
    if any(w in text_lower for w in ['погод', 'прогноз', 'дождь', 'ветер', 'температура', 'солнце']):
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
    if any(w in text_lower for w in ['время', 'часы', 'который час', 'дата', 'сегодня']):
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
    
    # AI ответ
    thinking = await update.message.reply_text("🤔 Думаю...")
    reply = await get_ai_response(text)
    await thinking.delete()
    await update.message.reply_text(reply, reply_markup=menu)

# ==================== ОБРАБОТЧИК ГОЛОСА ====================

async def handle_voice(update: Update, context):
    user_id = update.effective_user.id
    processing = await update.message.reply_text("🎤 Распознаю голосовое сообщение...")
    
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        audio = await file.download_as_bytearray()
        
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field('file', audio, filename='audio.ogg', content_type='audio/ogg')
            form.add_field('model', 'openai/whisper-large-v3-turbo')
            async with session.post(
                "https://openrouter.ai/api/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
                data=form,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    recognized = result.get("text", "").strip().lower()
                    logger.info(f"Recognized: {recognized}")
                    
                    if not recognized:
                        await processing.edit_text("😔 Не удалось распознать голос. Попробуйте говорить чётче.", reply_markup=menu)
                        return
                    
                    await processing.edit_text(f"📝 Вы сказали: {recognized}\n\n🤔 Обрабатываю...")
                    
                    # Погода
                    if any(w in recognized for w in ['погод', 'прогноз', 'дождь', 'ветер', 'температура', 'солнце']):
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
                    if any(w in recognized for w in ['время', 'часы', 'который час', 'дата', 'сегодня']):
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
                    
                    # AI ответ
                    ai_reply = await get_ai_response(recognized)
                    await processing.delete()
                    await update.message.reply_text(ai_reply, reply_markup=menu)
                    
                else:
                    await processing.edit_text("❌ Ошибка распознавания голоса. Попробуйте ещё раз.", reply_markup=menu)
                    
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
        "• Сказать «я живу в Москве» — запомнит город\n"
        "• Сказать любой вопрос — ответит через AI",
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
