import os
import re
import logging
import aiohttp
import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
WEATHER_KEY = os.environ.get("OPENWEATHER_API_KEY", "")

# ==================== КЛАВИАТУРА ====================

main_menu = ReplyKeyboardMarkup(
    [
        ["💬 Поговорить", "📅 Напоминания", "👥 События"],
        ["🆘 SOS", "👨‍👩‍👧 Семья", "⚙️ Настройки"],
        ["🌤️ Погода", "🎮 Игры", "📖 Ностальгия"]
    ],
    resize_keyboard=True,
)

# ==================== БАЗА ДАННЫХ ====================

def init_db():
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            name TEXT,
            city TEXT,
            role TEXT DEFAULT 'senior'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            text TEXT,
            time_local TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS family_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER,
            user2_id INTEGER,
            relation_type TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(telegram_id, name=None, city=None, role="senior"):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (telegram_id, name, city, role)
        VALUES (?, ?, ?, ?)
    """, (telegram_id, name, city, role))
    conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, city, role FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return {"name": row[0], "city": row[1], "role": row[2]} if row else None

def add_family_link(user1_id, user2_id, relation_type):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO family_links (user1_id, user2_id, relation_type) VALUES (?, ?, ?)", 
                       (user1_id, user2_id, relation_type))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def get_family_members(user_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT CASE WHEN user1_id = ? THEN user2_id ELSE user1_id END, relation_type
        FROM family_links WHERE user1_id = ? OR user2_id = ?
    """, (user_id, user_id, user_id))
    rows = cursor.fetchall()
    result = []
    for row in rows:
        cursor.execute("SELECT name FROM users WHERE telegram_id = ?", (row[0],))
        user_data = cursor.fetchone()
        if user_data:
            result.append({"id": row[0], "name": user_data[0] or f"User_{row[0]}", "relation": row[1]})
    conn.close()
    return result

def add_reminder(telegram_id, text, time_local):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reminders (telegram_id, text, time_local) VALUES (?, ?, ?)",
                   (telegram_id, text, time_local))
    conn.commit()
    conn.close()

def get_reminders(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT text, time_local FROM reminders WHERE telegram_id = ?", (telegram_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"text": r[0], "time": r[1]} for r in rows]

def log_activity(telegram_id, action):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO activities (telegram_id, action) VALUES (?, ?)", (telegram_id, action))
    conn.commit()
    conn.close()

def get_stats(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND action = 'talk'", (telegram_id,))
    talks = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND action = 'sos'", (telegram_id,))
    sos = cursor.fetchone()[0]
    conn.close()
    return {"talks": talks, "sos": sos}

# ==================== ПОГОДА ====================

async def get_weather(city: str) -> str:
    if not WEATHER_KEY:
        return None
    city_map = {"москва": "Moscow", "санкт-петербург": "Saint Petersburg", "новосибирск": "Novosibirsk"}
    city_en = city_map.get(city.lower(), city)
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city_en}&appid={WEATHER_KEY}&units=metric&lang=ru"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return (f"🌡️ *Погода в {data['name']}*\n\n"
                           f"🌡️ Температура: {round(data['main']['temp'])}°C\n"
                           f"💧 Влажность: {data['main']['humidity']}%\n"
                           f"💨 Ветер: {data['wind']['speed']} м/с")
    except:
        pass
    return None

# ==================== AI ОТВЕТ ====================

async def ai_chat(message: str) -> str:
    if not OPENROUTER_KEY:
        return None
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
    except:
        pass
    return None

# ==================== КОМАНДЫ ====================

async def start(update: Update, context):
    user_id = update.effective_user.id
    user = get_user(user_id)
    
    if not user:
        save_user(user_id, name=update.effective_user.first_name, role="senior")
        await update.message.reply_text(
            "👋 *Добро пожаловать в бот-компаньон «Семья»!*\n\n"
            "Я помогу вам:\n"
            "• 💬 Общаться — просто пишите\n"
            "• 🌤️ Узнавать погоду — /weather\n"
            "• 📅 Добавлять напоминания — /add_reminder\n"
            "• 👨‍👩‍👧 Связываться с родственниками — /family\n"
            "• 🆘 Вызывать помощь — /sos\n\n"
            "Вот главное меню:",
            parse_mode="Markdown", reply_markup=main_menu
        )
    else:
        await update.message.reply_text(
            f"👋 *С возвращением, {user['name']}!*\n\nВот главное меню:",
            parse_mode="Markdown", reply_markup=main_menu
        )

async def help_command(update: Update, context):
    await update.message.reply_text(
        "🤖 *Команды:*\n\n"
        "*/start* — начать\n"
        "*/help* — помощь\n"
        "*/weather* — погода\n"
        "*/add_reminder* — добавить напоминание\n"
        "*/reminders* — список напоминаний\n"
        "*/family* — семейное меню\n"
        "*/add_relative* — добавить родственника\n"
        "*/sos* — экстренная помощь\n\n"
        "Просто пишите — я отвечу! 💬",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def weather_command(update: Update, context):
    user = get_user(update.effective_user.id)
    city = user.get("city") if user else None
    if not city:
        await update.message.reply_text("🌤️ Скажите ваш город: *Мой город Москва*", parse_mode="Markdown", reply_markup=main_menu)
        return
    msg = await update.message.reply_text("🌤️ Узнаю погоду...")
    weather = await get_weather(city)
    await msg.delete()
    if weather:
        await update.message.reply_text(weather, parse_mode="Markdown", reply_markup=main_menu)
    else:
        await update.message.reply_text(f"😔 Не нашёл погоду для {city}", reply_markup=main_menu)

async def add_reminder(update: Update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 *Как добавить напоминание:*\n/add_reminder 09:00 Принять лекарство", parse_mode="Markdown")
        return
    time = args[0]
    text = " ".join(args[1:])
    add_reminder(update.effective_user.id, text, time)
    await update.message.reply_text(f"✅ Напоминание добавлено!\n\n🕐 *{time}* — {text}", parse_mode="Markdown", reply_markup=main_menu)

async def reminders_list(update: Update, context):
    reminders = get_reminders(update.effective_user.id)
    if not reminders:
        await update.message.reply_text("📋 У вас пока нет напоминаний.\n/add_reminder — добавить", reply_markup=main_menu)
        return
    lines = ["📋 *Ваши напоминания:*"]
    for r in reminders:
        lines.append(f"• {r['time']} — {r['text']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu)

async def family_command(update: Update, context):
    user_id = update.effective_user.id
    members = get_family_members(user_id)
    if not members:
        await update.message.reply_text(
            "👨‍👩‍👧 *У вас пока нет родственников*\n\n"
            "Добавьте через /add_relative ID бабушка",
            parse_mode="Markdown", reply_markup=main_menu
        )
        return
    text = "👨‍👩‍👧 *Ваши родственники:*\n\n"
    for m in members:
        text += f"• {m['name']} (ID: {m['id']}) — {m['relation']}\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu)

async def add_relative(update: Update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 *Как добавить родственника:*\n/add_relative 123456789 бабушка", parse_mode="Markdown")
        return
    try:
        relative_id = int(args[0])
        relation = args[1].lower()
        user_id = update.effective_user.id
        if add_family_link(user_id, relative_id, relation):
            await update.message.reply_text(f"✅ Родственник добавлен!\n\nID: {relative_id}\nСвязь: {relation}", reply_markup=main_menu)
        else:
            await update.message.reply_text("❌ Ошибка при добавлении", reply_markup=main_menu)
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом!", reply_markup=main_menu)

async def sos_command(update: Update, context):
    user_id = update.effective_user.id
    log_activity(user_id, "sos")
    user = get_user(user_id)
    user_name = user["name"] if user else "Родственник"
    
    members = get_family_members(user_id)
    notified = 0
    for member in members:
        try:
            await context.bot.send_message(member["id"], f"🚨 *ВНИМАНИЕ!*\n\n{user_name} нажал(а) SOS!", parse_mode="Markdown")
            notified += 1
        except:
            pass
    
    await update.message.reply_text(f"🆘 *SOS отправлен!*\n\nУведомлено: {notified}", parse_mode="Markdown", reply_markup=main_menu)

async def events_command(update: Update, context):
    await update.message.reply_text(
        "👥 *События:*\n\n• 🎨 Рисование — вторник 15:00\n• 🧘 Зарядка — среда 10:00\n• 📚 Книжный клуб — пятница 16:00",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def games_command(update: Update, context):
    await update.message.reply_text("🎮 *Игры:*\n\nСкоро будут доступны!", parse_mode="Markdown", reply_markup=main_menu)

async def nostalgia_command(update: Update, context):
    await update.message.reply_text("📖 *Ностальгия:*\n\n• 🎬 Советское кино\n• 🎵 Старые песни", parse_mode="Markdown", reply_markup=main_menu)

async def settings_command(update: Update, context):
    await update.message.reply_text(
        "⚙️ *Настройки:*\n\n• /weather — погода\n• /add_reminder — напоминания\n• /family — семья",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def set_city(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.lower()
    match = re.search(r'(мой город|живу в|город)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', text)
    if match:
        city = match.group(2).strip().capitalize()
        if len(city) > 1:
            user = get_user(user_id)
            save_user(user_id, name=user["name"] if user else update.effective_user.first_name, city=city)
            await update.message.reply_text(f"✅ Запомнила! Город: *{city}*", parse_mode="Markdown", reply_markup=main_menu)

async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text and text[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️", "🌤️", "🎮", "📖"]:
        text = text[1:].strip()
        if not text:
            await update.message.reply_text("Напишите что-нибудь! 😊", reply_markup=main_menu)
            return
    
    text_lower = text.lower()
    
    if text_lower in ['погода', 'погоду']:
        await weather_command(update, context)
        return
    if text_lower in ['время', 'который час']:
        now = datetime.now()
        await update.message.reply_text(f"📅 *{now.strftime('%d.%m.%Y')}*\n🕐 *{now.strftime('%H:%M')}*", parse_mode="Markdown", reply_markup=main_menu)
        return
    if text_lower in ['привет', 'здравствуй']:
        await update.message.reply_text(f"Привет! 🌷\n\nЧем могу помочь?", reply_markup=main_menu)
        return
    if 'мой город' in text_lower or 'живу в' in text_lower:
        await set_city(update, context)
        return
    if text_lower in ['помощь', 'help']:
        await help_command(update, context)
        return
    
    log_activity(user_id, "talk")
    msg = await update.message.reply_text("🤔 Думаю...")
    reply = await ai_chat(text)
    await msg.delete()
    
    if reply:
        await update.message.reply_text(reply, reply_markup=main_menu)
    else:
        await update.message.reply_text(
            "😊 *Я вас понял!*\n\n"
            "• *погода* — узнать погоду\n"
            "• *время* — узнать время\n"
            "• *мой город Москва* — запомнить город\n"
            "• /help — все команды",
            parse_mode="Markdown", reply_markup=main_menu
        )

async def handle_voice(update: Update, context):
    await update.message.reply_text(
        "🎤 *Голосовое сообщение получено!*\n\nПожалуйста, напишите текстом! 😊",
        parse_mode="Markdown", reply_markup=main_menu
    )

# ==================== ЗАПУСК ====================

def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан!")
        return
    
    init_db()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("add_reminder", add_reminder))
    app.add_handler(CommandHandler("reminders", reminders_list))
    app.add_handler(CommandHandler("family", family_command))
    app.add_handler(CommandHandler("add_relative", add_relative))
    app.add_handler(CommandHandler("sos", sos_command))
    app.add_handler(CommandHandler("events", events_command))
    app.add_handler(CommandHandler("games", games_command))
    app.add_handler(CommandHandler("nostalgia", nostalgia_command))
    app.add_handler(CommandHandler("settings", settings_command))
    
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
