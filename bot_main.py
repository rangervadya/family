import os
import re
import logging
import aiohttp
import sqlite3
from datetime import datetime, time
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, filters, JobQueue
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
WEATHER_KEY = os.environ.get("OPENWEATHER_API_KEY", "")

# ==================== КЛАВИАТУРА ====================

main_menu = ReplyKeyboardMarkup(
    [
        ["💬 Поговорить", "📅 Напоминания", "👥 События"],
        ["🆘 ПОМОЩЬ", "👨‍👩‍👧 Семья", "⚙️ Настройки"],
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
            age INTEGER,
            city TEXT,
            interests TEXT,
            role TEXT DEFAULT 'senior'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            kind TEXT,
            text TEXT,
            time_local TEXT,
            enabled INTEGER DEFAULT 1
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
        CREATE TABLE IF NOT EXISTS relatives (
            senior_id INTEGER,
            relative_id INTEGER,
            PRIMARY KEY (senior_id, relative_id)
        )
    """)
    conn.commit()
    conn.close()

def save_user(telegram_id, name=None, age=None, city=None, interests=None, role="senior"):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO users (telegram_id, name, age, city, interests, role)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (telegram_id, name, age, city, interests, role))
    conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, age, city, interests, role FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return {"name": row[0], "age": row[1], "city": row[2], "interests": row[3], "role": row[4]} if row else None

def add_reminder(telegram_id, kind, text, time_local):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reminders (telegram_id, kind, text, time_local) VALUES (?, ?, ?, ?)",
                   (telegram_id, kind, text, time_local))
    conn.commit()
    conn.close()

def get_reminders(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, kind, text, time_local, enabled FROM reminders WHERE telegram_id = ?", (telegram_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "kind": r[1], "text": r[2], "time": r[3], "enabled": r[4]} for r in rows]

def log_activity(telegram_id, action):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO activities (telegram_id, action) VALUES (?, ?)", (telegram_id, action))
    conn.commit()
    conn.close()

def get_stats(telegram_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND action = 'talk' AND created_at > datetime('now', '-1 day')", (telegram_id,))
    talks = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND action = 'reminder_done' AND created_at > datetime('now', '-1 day')", (telegram_id,))
    meds = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND action = 'sos' AND created_at > datetime('now', '-1 day')", (telegram_id,))
    sos = cursor.fetchone()[0]
    conn.close()
    return {"talks": talks, "meds": meds, "sos": sos}

def add_relative(senior_id, relative_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO relatives (senior_id, relative_id) VALUES (?, ?)", (senior_id, relative_id))
    conn.commit()
    conn.close()

def get_relatives(senior_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT relative_id FROM relatives WHERE senior_id = ?", (senior_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ==================== ПОГОДА ====================

async def get_weather(city: str) -> str:
    if not WEATHER_KEY:
        return None
    city_map = {"москва": "Moscow", "санкт-петербург": "Saint Petersburg", "новосибирск": "Novosibirsk",
                "екатеринбург": "Yekaterinburg", "казань": "Kazan", "краснодар": "Krasnodar", "сочи": "Sochi"}
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
                           f"💨 Ветер: {data['wind']['speed']} м/с\n"
                           f"📖 {data['weather'][0]['description'].capitalize()}")
    except: pass
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
                json={"model": "qwen/qwen3.6-plus-preview:free", "messages": [{"role": "user", "content": message}], "max_tokens": 500},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
    except: pass
    return None

# ==================== КОМАНДЫ ====================

async def start(update: Update, context):
    user = update.effective_user
    save_user(user.id, name=user.first_name, role="senior")
    await update.message.reply_text(
        "👋 *Добро пожаловать в бот-компаньон «Семья»!*\n\n"
        "Я помогу вам:\n"
        "• 💬 *Общаться* — просто пишите\n"
        "• 📅 *Напоминания* — /add_reminder\n"
        "• 👥 *События* — /events\n"
        "• 🆘 *SOS* — экстренная помощь\n"
        "• 👨‍👩‍👧 *Семья* — связать родственников\n"
        "• 🌤️ *Погода* — /weather\n"
        "• 🎮 *Игры* — /games\n"
        "• 📖 *Ностальгия* — /nostalgia\n"
        "• 📚 *Курсы* — /courses\n"
        "• 🏆 *Достижения* — /achievements\n\n"
        "Начните общение прямо сейчас! 😊",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def help_command(update: Update, context):
    await update.message.reply_text(
        "🤖 *Список команд:*\n\n"
        "*/start* — начать заново\n"
        "*/help* — эта справка\n"
        "*/weather* — погода в вашем городе\n"
        "*/add_reminder* — добавить напоминание\n"
        "*/reminders* — список напоминаний\n"
        "*/events* — анонсы событий\n"
        "*/companions* — поиск компаньонов\n"
        "*/volunteers* — волонтёрская помощь\n"
        "*/health_extra* — дополнительная информация о здоровье\n"
        "*/helper* — помощь по дому\n"
        "*/games* — игры\n"
        "*/nostalgia* — ностальгия\n"
        "*/courses* — курсы\n"
        "*/achievements* — достижения\n"
        "*/voice_help* — голосовой помощник\n"
        "*/family* — семейная статистика\n"
        "*/sos* — экстренная помощь\n\n"
        "Просто пишите мне сообщения — я отвечу! 💬",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def menu_command(update: Update, context):
    await update.message.reply_text("📋 *Главное меню:*", parse_mode="Markdown", reply_markup=main_menu)

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

async def add_reminder_start(update: Update, context):
    await update.message.reply_text("💊 *Когда напоминать?*\nНапишите время в формате ЧЧ:ММ, например 09:00", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return 1

async def add_reminder_time(update: Update, context):
    text = update.message.text
    if not re.match(r'^\d{2}:\d{2}$', text):
        await update.message.reply_text("❌ Неверный формат. Напишите ЧЧ:ММ, например 14:30")
        return 1
    context.user_data["reminder_time"] = text
    await update.message.reply_text("💊 *Что напоминать?*\nНапример: «Принять таблетку от давления»", parse_mode="Markdown")
    return 2

async def add_reminder_text(update: Update, context):
    user_id = update.effective_user.id
    time = context.user_data.get("reminder_time")
    text = update.message.text
    add_reminder(user_id, "meds", text, time)
    await update.message.reply_text(f"✅ Напоминание добавлено!\n\n🕐 *{time}* — {text}", parse_mode="Markdown", reply_markup=main_menu)
    return -1

async def reminders_list(update: Update, context):
    user_id = update.effective_user.id
    reminders = get_reminders(user_id)
    if not reminders:
        await update.message.reply_text("📋 У вас пока нет напоминаний.\n\n/add_reminder — добавить", reply_markup=main_menu)
        return
    lines = ["📋 *Ваши напоминания:*"]
    for r in reminders:
        lines.append(f"• {r['time']} — {r['text']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu)

async def events_command(update: Update, context):
    await update.message.reply_text(
        "👥 *Активные события:*\n\n"
        "• 🎨 *Кружок рисования* — вторник 15:00\n"
        "• 🧘 *Зарядка для здоровья* — среда 10:00\n"
        "• 📚 *Книжный клуб* — пятница 16:00\n"
        "• 🎭 *Театральная гостиная* — воскресенье 14:00\n\n"
        "Участвуйте! 🌟",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def companions_command(update: Update, context):
    await update.message.reply_text(
        "👥 *Поиск компаньонов*\n\n"
        "Здесь вы можете найти друзей для прогулок, общения и совместных занятий.\n\n"
        "Скоро здесь появятся анкеты участников! 🌟",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def volunteers_command(update: Update, context):
    await update.message.reply_text(
        "🤝 *Волонтёрская помощь*\n\n"
        "Волонтёры могут помочь:\n"
        "• Сходить в магазин\n"
        "• Сопроводить к врачу\n"
        "• Помочь с компьютером\n"
        "• Просто поболтать\n\n"
        "Свяжитесь с координатором: @VolunteerHelp",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def health_extra_command(update: Update, context):
    await update.message.reply_text(
        "💊 *О здоровье*\n\n"
        "• Регулярно измеряйте давление\n"
        "• Пейте больше воды (1.5-2 л в день)\n"
        "• Не пропускайте приём лекарств\n"
        "• Больше двигайтесь\n"
        "• Высыпайтесь (7-8 часов)\n\n"
        "Берегите себя! ❤️",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def helper_command(update: Update, context):
    await update.message.reply_text(
        "🏠 *Помощь по дому*\n\n"
        "Сервисы помощи:\n"
        "• 🛒 Доставка продуктов — СберМаркет, Купер\n"
        "• 💊 Доставка лекарств — Здравсити, Мегаптека\n"
        "• 🧹 Клининг — Qlean, Химчистка №1\n"
        "• 👨‍⚕️ Сиделка — сервис «Забота»\n\n"
        "Нужна помощь? Напишите — подскажу!",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def games_command(update: Update, context):
    await update.message.reply_text(
        "🎮 *Игры для вас:*\n\n"
        "• 🃏 *Слова* — назовите слово на последнюю букву\n"
        "• 🧩 *Загадки* — отгадывайте загадки\n"
        "• 📖 *Цитаты* — угадайте автора\n"
        "• 🎲 *Кости* — сыграйте со мной\n\n"
        "Напишите *играть* — начнём! 🎉",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def nostalgia_command(update: Update, context):
    await update.message.reply_text(
        "📖 *Ностальгия*\n\n"
        "Вспомним прошлое:\n"
        "• 🎬 *Советское кино* — «Ирония судьбы», «Москва слезам не верит»\n"
        "• 🎵 *Песни* — «Катюша», «День Победы»\n"
        "• 📚 *Книги* — «Как закалялась сталь», «Тихий Дон»\n"
        "• 📻 *Радио* — «В рабочий полдень»\n\n"
        "Хотите послушать старую песню? Напишите название!",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def courses_command(update: Update, context):
    await update.message.reply_text(
        "📚 *Бесплатные курсы:*\n\n"
        "• 📱 *Компьютерная грамотность* — онлайн\n"
        "• 🎨 *Рисование* — вторник/четверг\n"
        "• 🧘 *Здоровье* — зарядка онлайн\n"
        "• 🌸 *Рукоделие* — вязание, вышивка\n"
        "• 📖 *Английский* — для начинающих\n\n"
        "Запишитесь через команду /courses_signup",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def achievements_command(update: Update, context):
    user_id = update.effective_user.id
    stats = get_stats(user_id)
    await update.message.reply_text(
        f"🏆 *Ваши достижения:*\n\n"
        f"💬 Диалогов: *{stats['talks']}*\n"
        f"💊 Приёмов лекарств: *{stats['meds']}*\n"
        f"🆘 SOS отправлено: *{stats['sos']}*\n\n"
        f"Так держать! 🌟",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def voice_help_command(update: Update, context):
    await update.message.reply_text(
        "🎤 *Голосовой помощник*\n\n"
        "Вы можете отправлять голосовые сообщения!\n\n"
        "• Нажмите на 🎤 в Telegram\n"
        "• Скажите что хотите (например, «Какая погода?»)\n"
        "• Я распознаю и отвечу\n\n"
        "Скоро эта функция заработает в полную силу!",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def family_command(update: Update, context):
    user_id = update.effective_user.id
    stats = get_stats(user_id)
    relatives = get_relatives(user_id)
    await update.message.reply_text(
        f"👨‍👩‍👧 *Семейная статистика:*\n\n"
        f"💬 Диалогов: *{stats['talks']}*\n"
        f"💊 Приём лекарств: *{stats['meds']}*\n"
        f"🆘 SOS: *{stats['sos']}*\n"
        f"👨‍👩‍👧 Связанных родственников: *{len(relatives)}*\n\n"
        "Команда /add_relative <id> — добавить родственника",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def sos_command(update: Update, context):
    user_id = update.effective_user.id
    log_activity(user_id, "sos")
    relatives = get_relatives(user_id)
    for rel_id in relatives:
        try:
            await context.bot.send_message(rel_id, f"🚨 *ВНИМАНИЕ!*\n\nВаш близкий человек нажал SOS!\nСвяжитесь с ним как можно скорее!", parse_mode="Markdown")
        except: pass
    await update.message.reply_text(
        "🆘 *Сигнал SOS отправлен!*\n\n"
        "Я уведомила ваших близких.\n"
        "Если нужна срочная помощь — звоните 112!",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def add_relative_command(update: Update, context):
    if not context.args:
        await update.message.reply_text("👨‍👩‍👧 *Как привязать родственника:*\n\n/add_relative <Telegram ID>\n\nПример: /add_relative 123456789", parse_mode="Markdown")
        return
    try:
        senior_id = int(context.args[0])
        relative_id = update.effective_user.id
        add_relative(senior_id, relative_id)
        await update.message.reply_text(f"✅ Вы привязаны к пользователю {senior_id}!", reply_markup=main_menu)
    except:
        await update.message.reply_text("❌ Ошибка! ID должен быть числом.", reply_markup=main_menu)

async def set_city(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.lower()
    match = re.search(r'(мой город|живу в|город)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', text)
    if match:
        city = match.group(2).strip().capitalize()
        if len(city) > 1:
            user = get_user(user_id) or {}
            save_user(user_id, name=user.get("name"), age=user.get("age"), city=city, interests=user.get("interests"))
            await update.message.reply_text(f"✅ Запомнила! Твой город: *{city}*", parse_mode="Markdown", reply_markup=main_menu)

async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Убираем эмодзи меню
    if text and text[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️", "🌤️", "🎮", "📖"]:
        text = text[1:].strip()
        if not text:
            await update.message.reply_text("Напиши что-нибудь, и мы поговорим! 😊", reply_markup=main_menu)
            return
    
    text_lower = text.lower()
    
    # Обработка команд из чата
    if text_lower in ['погода', 'погоду', 'какая погода']:
        await weather_command(update, context)
        return
    if text_lower in ['время', 'который час', 'сколько времени']:
        now = datetime.now()
        await update.message.reply_text(f"📅 *{now.strftime('%d.%m.%Y')}*\n🕐 *{now.strftime('%H:%M')}*", parse_mode="Markdown", reply_markup=main_menu)
        return
    if text_lower in ['привет', 'здравствуй', 'здравствуйте']:
        await update.message.reply_text(f"Привет! 🌷\n\nКак у тебя дела? Чем могу помочь?", reply_markup=main_menu)
        return
    if 'мой город' in text_lower or 'живу в' in text_lower:
        await set_city(update, context)
        return
    if text_lower in ['помощь', 'help']:
        await help_command(update, context)
        return
    
    # AI ответ
    log_activity(user_id, "talk")
    msg = await update.message.reply_text("🤔 Думаю...")
    reply = await ai_chat(text)
    await msg.delete()
    
    if reply:
        await update.message.reply_text(reply, reply_markup=main_menu)
    else:
        await update.message.reply_text(
            "😊 *Я тебя услышал!*\n\n"
            "Мои команды:\n"
            "• *погода* — узнать погоду\n"
            "• *время* — узнать время\n"
            "• *мой город Москва* — запомнить город\n"
            "• /help — все команды\n\n"
            "Просто поговори со мной! 💬",
            parse_mode="Markdown", reply_markup=main_menu
        )

async def handle_voice(update: Update, context):
    await update.message.reply_text(
        "🎤 *Голосовое сообщение получено!*\n\n"
        "Я пока учусь распознавать голос.\n"
        "Пожалуйста, напиши текстом — я отвечу! 😊\n\n"
        "Мои команды:\n"
        "• *погода* — узнать погоду\n"
        "• *время* — узнать время\n"
        "• /help — все команды",
        parse_mode="Markdown", reply_markup=main_menu
    )

# ==================== ЕЖЕДНЕВНЫЕ НАПОМИНАНИЯ ====================

async def daily_checkin(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=context.job.chat_id, text="🌞 *Доброе утро!*\n\nКак вы себя сегодня чувствуете?", parse_mode="Markdown")

async def enable_checkin(update: Update, context):
    chat_id = update.effective_chat.id
    context.job_queue.run_daily(daily_checkin, time=time(hour=10, minute=0), chat_id=chat_id, name=str(chat_id))
    await update.message.reply_text("✅ Ежедневный опрос включён! Я буду спрашивать в 10:00.", reply_markup=main_menu)

# ==================== ЗАПУСК ====================

def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан!")
        return
    
    init_db()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("reminders", reminders_list))
    app.add_handler(CommandHandler("events", events_command))
    app.add_handler(CommandHandler("companions", companions_command))
    app.add_handler(CommandHandler("volunteers", volunteers_command))
    app.add_handler(CommandHandler("health_extra", health_extra_command))
    app.add_handler(CommandHandler("helper", helper_command))
    app.add_handler(CommandHandler("games", games_command))
    app.add_handler(CommandHandler("nostalgia", nostalgia_command))
    app.add_handler(CommandHandler("courses", courses_command))
    app.add_handler(CommandHandler("achievements", achievements_command))
    app.add_handler(CommandHandler("voice_help", voice_help_command))
    app.add_handler(CommandHandler("family", family_command))
    app.add_handler(CommandHandler("sos", sos_command))
    app.add_handler(CommandHandler("add_relative", add_relative_command))
    app.add_handler(CommandHandler("enable_checkin", enable_checkin))
    
    # Conversation для напоминаний
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add_reminder", add_reminder_start)],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_time)],
                2: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_text)]},
        fallbacks=[]
    )
    app.add_handler(conv_handler)
    
    # Обработчики сообщений
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
