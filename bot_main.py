import os
import logging
import aiohttp
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

# Хранилище пользователей
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
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    temp = round(data['main']['temp'])
                    feels = round(data['main']['feels_like'])
                    humidity = data['main']['humidity']
                    wind = data['wind']['speed']
                    desc = data['weather'][0]['description']
                    name = data['name']
                    return (f"🌡️ *Погода в {name}*\n\n"
                           f"🌡️ Температура: {temp}°C\n"
                           f"🤔 Ощущается как: {feels}°C\n"
                           f"💧 Влажность: {humidity}%\n"
                           f"💨 Ветер: {wind} м/с\n"
                           f"📖 {desc.capitalize()}")
    except Exception as e:
        logger.error(f"Weather error: {e}")
    return None

# ==================== AI ОТВЕТ ====================

async def ai_chat(message: str) -> str:
    """Ответ через OpenRouter AI"""
    if not OPENROUTER_KEY:
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "qwen/qwen3.6-plus-preview:free",
                    "messages": [
                        {"role": "system", "content": "Ты дружелюбный бот-компаньон. Отвечай кратко, тепло и по-русски."},
                        {"role": "user", "content": message}
                    ],
                    "max_tokens": 300
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"AI error: {e}")
    return None

# ==================== ОБРАБОТЧИКИ ====================

async def start(update: Update, context):
    user_id = update.effective_user.id
    user_data[user_id] = user_data.get(user_id, {})
    
    await update.message.reply_text(
        "🤖 *Бот-компаньон «Семья»*\n\n"
        "Я умею:\n"
        "• 💬 *Общаться* — просто напиши что угодно\n"
        "• 🌤️ *Погода* — отправь /weather или напиши «погода»\n"
        "• 🕐 *Время* — напиши «время»\n"
        "• 🎤 *Голос* — отправь голосовое сообщение\n\n"
        "Давай пообщаемся! 😊",
        parse_mode="Markdown", reply_markup=menu
    )

async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Убираем эмодзи меню
    if text and text[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️"]:
        text = text[1:].strip()
        if not text:
            await update.message.reply_text("Напиши что-нибудь, и мы поговорим! 😊", reply_markup=menu)
            return
    
    text_lower = text.lower()
    
    # === КОМАНДЫ ===
    
    # Погода
    if text_lower in ['погода', 'погоду', 'какая погода', 'что с погодой', '/weather']:
        city = user_data.get(user_id, {}).get("city")
        if not city:
            await update.message.reply_text(
                "🌤️ Я не знаю твой город.\n"
                "Напиши: *Мой город Москва*\n\n"
                "Я запомню и буду показывать погоду!",
                parse_mode="Markdown", reply_markup=menu
            )
            return
        
        msg = await update.message.reply_text("🌤️ Узнаю погоду...")
        weather = await get_weather(city)
        await msg.delete()
        
        if weather:
            await update.message.reply_text(weather, parse_mode="Markdown", reply_markup=menu)
        else:
            await update.message.reply_text(f"😔 Не нашёл погоду для {city}. Проверь название города.", reply_markup=menu)
        return
    
    # Время
    if text_lower in ['время', 'который час', 'сколько времени', 'часы', 'дата']:
        now = datetime.now()
        await update.message.reply_text(
            f"📅 *{now.strftime('%d.%m.%Y')}*\n"
            f"🕐 *{now.strftime('%H:%M')}*",
            parse_mode="Markdown", reply_markup=menu
        )
        return
    
    # Запоминаем город
    if 'мой город' in text_lower or 'живу в' in text_lower or 'город' in text_lower:
        import re
        match = re.search(r'(?:мой город|живу в|город)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', text_lower)
        if match:
            city = match.group(1).strip().capitalize()
            if len(city) > 1:
                if user_id not in user_data:
                    user_data[user_id] = {}
                user_data[user_id]["city"] = city
                await update.message.reply_text(f"✅ Запомнила! Твой город: *{city}*\n\nТеперь спрашивай погоду!", parse_mode="Markdown", reply_markup=menu)
                return
    
    # Приветствие
    if text_lower in ['привет', 'здравствуй', 'здравствуйте', 'доброе утро', 'добрый день', 'добрый вечер']:
        await update.message.reply_text(
            f"Привет! 🌷\n\n"
            f"Как у тебя дела? Чем могу помочь?",
            reply_markup=menu
        )
        return
    
    # === AI ОТВЕТ ===
    msg = await update.message.reply_text("🤔 Думаю...")
    reply = await ai_chat(text)
    await msg.delete()
    
    if reply:
        await update.message.reply_text(reply, reply_markup=menu)
    else:
        await update.message.reply_text(
            f"😊 Я тебя услышал!\n\n"
            f"Мои команды:\n"
            f"• *погода* — узнать погоду\n"
            f"• *время* — узнать время\n"
            f"• *мой город Москва* — запомнить город\n\n"
            f"Или просто поговори со мной!",
            parse_mode="Markdown", reply_markup=menu
        )

async def handle_voice(update: Update, context):
    """Простой ответ на голосовые сообщения"""
    await update.message.reply_text(
        "🎤 Спасибо за голосовое сообщение!\n\n"
        "К сожалению, я пока не умею распознавать голос.\n\n"
        "Пожалуйста, напиши текстом, и я с радостью отвечу! 😊\n\n"
        "Мои команды:\n"
        "• *погода* — узнать погоду\n"
        "• *время* — узнать время\n"
        "• *мой город Москва* — запомнить город",
        parse_mode="Markdown", reply_markup=menu
    )

async def weather_command(update: Update, context):
    user_id = update.effective_user.id
    city = user_data.get(user_id, {}).get("city")
    
    if not city:
        await update.message.reply_text(
            "🌤️ Я не знаю твой город.\n"
            "Напиши: *Мой город Москва*",
            parse_mode="Markdown", reply_markup=menu
        )
        return
    
    msg = await update.message.reply_text("🌤️ Узнаю погоду...")
    weather = await get_weather(city)
    await msg.delete()
    
    if weather:
        await update.message.reply_text(weather, parse_mode="Markdown", reply_markup=menu)
    else:
        await update.message.reply_text(f"😔 Не нашёл погоду для {city}.", reply_markup=menu)

async def help_command(update: Update, context):
    await update.message.reply_text(
        "🤖 *Бот-компаньон «Семья»*\n\n"
        "*Команды:*\n"
        "• `/start` — начать заново\n"
        "• `/help` — эта справка\n"
        "• `/weather` — погода\n\n"
        "*Что я умею:*\n"
        "• 💬 *Общаться* — напиши что угодно\n"
        "• 🌤️ *Погода* — напиши «погода»\n"
        "• 🕐 *Время* — напиши «время»\n"
        "• 🌆 *Город* — напиши «мой город Москва»\n\n"
        "Просто напиши мне! 😊",
        parse_mode="Markdown", reply_markup=menu
    )

async def menu_command(update: Update, context):
    await update.message.reply_text("📋 *Главное меню:*", parse_mode="Markdown", reply_markup=menu)

# ==================== ЗАПУСК ====================

def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("weather", weather_command))
    
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
