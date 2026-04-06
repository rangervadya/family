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
        ["🆘 SOS", "👨‍👩‍👧 Семья", "⚙️ Настройки"],
        ["🌤️ Погода", "🎮 Игры", "📖 Ностальгия"]
    ],
    resize_keyboard=True,
)

family_menu = ReplyKeyboardMarkup(
    [
        ["👵 Мои бабушки/дедушки", "👶 Мои внуки/дети"],
        ["➕ Добавить родственника", "📊 Статистика семьи"],
        ["🔙 Назад в меню"]
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
        CREATE TABLE IF NOT EXISTS family_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER,
            user2_id INTEGER,
            relation_type TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user1_id, user2_id)
        )
    """)
    
    conn.commit()
    conn.close()

# ==================== РАБОТА С БАЗОЙ ====================

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

def add_family_link(user1_id, user2_id, relation_type):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO family_links (user1_id, user2_id, relation_type, status)
            VALUES (?, ?, ?, 'active')
        """, (user1_id, user2_id, relation_type))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Add family link error: {e}")
        return False
    finally:
        conn.close()

def get_family_members(user_id):
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            CASE 
                WHEN user1_id = ? THEN user2_id
                ELSE user1_id
            END as relative_id,
            relation_type
        FROM family_links 
        WHERE (user1_id = ? OR user2_id = ?) AND status = 'active'
    """, (user_id, user_id, user_id))
    rows = cursor.fetchall()
    
    result = []
    for row in rows:
        relative_id = row[0]
        relation = row[1]
        cursor.execute("SELECT name, role FROM users WHERE telegram_id = ?", (relative_id,))
        user_data = cursor.fetchone()
        if user_data:
            result.append({
                "id": relative_id,
                "name": user_data[0] or f"User_{relative_id}",
                "role": user_data[1],
                "relation": relation
            })
    conn.close()
    return result

def get_family_stats(user_id):
    members = get_family_members(user_id)
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    
    stats = {"members": members, "sos_alerts": 0, "total_activities": 0}
    
    for member in members:
        cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND action = 'sos' AND created_at > datetime('now', '-7 days')", (member["id"],))
        stats["sos_alerts"] += cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM activities WHERE telegram_id = ? AND created_at > datetime('now', '-7 days')", (member["id"],))
        stats["total_activities"] += cursor.fetchone()[0]
    
    conn.close()
    return stats

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

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================

async def start(update: Update, context):
    """Начало работы с ботом"""
    user_id = update.effective_user.id
    
    # Очищаем данные сессии
    context.user_data.clear()
    
    # Проверяем, есть ли пользователь в БД
    user = get_user(user_id)
    
    if user:
        role_text = "пожилой пользователь" if user["role"] == "senior" else "родственник"
        await update.message.reply_text(
            f"👋 *С возвращением, {user['name'] or 'друг'}!*\n\n"
            f"Вы зарегистрированы как {role_text}.\n\n"
            f"Вот главное меню:",
            parse_mode="Markdown", reply_markup=main_menu
        )
    else:
        keyboard = [["Я пожилой пользователь", "Я родственник"]]
        await update.message.reply_text(
            "👋 *Добро пожаловать в бот-компаньон «Семья»!*\n\n"
            "Давайте познакомимся.\n"
            "Кто вы?",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
        return 1
    
    return -1

async def role_choice(update: Update, context):
    """Обработка выбора роли"""
    text = update.message.text.lower()
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    if "родственник" in text:
        save_user(user_id, name=user_name, role="relative")
        await update.message.reply_text(
            "👨‍👩‍👧 *Вы выбрали роль «Родственник»*\n\n"
            "Теперь вы можете:\n"
            "• Привязаться к пожилому родственнику через /add_relative\n"
            "• Получать уведомления о его активности\n"
            "• Отправлять сообщения через /id\n\n"
            "Вот главное меню:",
            parse_mode="Markdown", reply_markup=main_menu
        )
    else:
        save_user(user_id, name=user_name, role="senior")
        await update.message.reply_text(
            "👵 *Вы выбрали роль «Пожилой пользователь»*\n\n"
            "Теперь вы можете:\n"
            "• Общаться со мной\n"
            "• Добавлять напоминания через /add_reminder\n"
            "• Получать помощь и поддержку\n\n"
            "Вот главное меню:",
            parse_mode="Markdown", reply_markup=main_menu
        )
    
    return -1

async def family_menu_handler(update: Update, context):
    text = update.message.text
    
    if text == "👵 Мои бабушки/дедушки":
        await show_seniors(update, context)
    elif text == "👶 Мои внуки/дети":
        await show_children(update, context)
    elif text == "➕ Добавить родственника":
        await add_relative_start(update, context)
    elif text == "📊 Статистика семьи":
        await family_stats(update, context)
    elif text == "🔙 Назад в меню":
        await update.message.reply_text("📋 *Главное меню:*", parse_mode="Markdown", reply_markup=main_menu)

async def show_seniors(update: Update, context):
    user_id = update.effective_user.id
    members = get_family_members(user_id)
    seniors = [m for m in members if m["role"] == "senior"]
    
    if not seniors:
        await update.message.reply_text(
            "👵 *У вас пока нет связанных бабушек/дедушек*\n\n"
            "Используйте команду /add_relative <id> бабушка",
            parse_mode="Markdown", reply_markup=family_menu
        )
        return
    
    text = "👵 *Ваши бабушки и дедушки:*\n\n"
    for s in seniors:
        text += f"• {s['name']} (ID: {s['id']}) — {s['relation']}\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=family_menu)

async def show_children(update: Update, context):
    user_id = update.effective_user.id
    members = get_family_members(user_id)
    children = [m for m in members if m["role"] == "relative"]
    
    if not children:
        await update.message.reply_text(
            "👶 *У вас пока нет связанных внуков/детей*\n\n"
            "Попросите их добавить вас через /add_relative",
            parse_mode="Markdown", reply_markup=family_menu
        )
        return
    
    text = "👶 *Ваши внуки и дети:*\n\n"
    for c in children:
        text += f"• {c['name']} (ID: {c['id']}) — {c['relation']}\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=family_menu)

async def add_relative_start(update: Update, context):
    await update.message.reply_text(
        "👨‍👩‍👧 *Добавление родственника*\n\n"
        "Введите команду: `/add_relative ID тип`\n\n"
        "Пример: `/add_relative 123456789 бабушка`\n\n"
        "Типы: бабушка, дедушка, внук, внучка, дочь, сын",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )
    return 1

async def add_relative_id(update: Update, context):
    text = update.message.text.strip()
    parts = text.split()
    
    if len(parts) < 2:
        await update.message.reply_text("❌ Формат: `/add_relative ID тип`", parse_mode="Markdown")
        return 1
    
    try:
        relative_id = int(parts[0])
        relation_type = parts[1].lower()
        
        valid_relations = ["бабушка", "дедушка", "внук", "внучка", "дочь", "сын", "мама", "папа"]
        if relation_type not in valid_relations:
            await update.message.reply_text(f"❌ Неверный тип. Доступные: {', '.join(valid_relations)}")
            return 1
        
        user_id = update.effective_user.id
        
        if add_family_link(user_id, relative_id, relation_type):
            await update.message.reply_text(
                f"✅ *Родственник добавлен!*\n\n"
                f"ID: {relative_id}\n"
                f"Связь: {relation_type}",
                parse_mode="Markdown", reply_markup=family_menu
            )
        else:
            await update.message.reply_text("❌ Ошибка при добавлении.", reply_markup=family_menu)
        
        return -1
        
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом!", reply_markup=family_menu)
        return 1

async def family_stats(update: Update, context):
    user_id = update.effective_user.id
    stats = get_family_stats(user_id)
    user = get_user(user_id)
    
    text = f"👨‍👩‍👧 *Семейная статистика*\n\n"
    text += f"👤 *Вы:* {user['name'] if user else 'Неизвестно'}\n"
    text += f"👨‍👩‍👧 *Родственников:* {len(stats['members'])}\n"
    text += f"🆘 *SOS за неделю:* {stats['sos_alerts']}\n"
    text += f"💬 *Активность семьи:* {stats['total_activities']}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=family_menu)

async def send_to_relative(update: Update, context):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("📝 /id <ID> <сообщение>\nПример: /id 123456789 Привет", parse_mode="Markdown")
        return
    
    try:
        target_id = int(context.args[0])
        message = " ".join(context.args[1:])
        
        members = get_family_members(update.effective_user.id)
        is_relative = any(m["id"] == target_id for m in members)
        
        if not is_relative:
            await update.message.reply_text("❌ Этот пользователь не является вашим родственником!", reply_markup=family_menu)
            return
        
        sender = get_user(update.effective_user.id)
        sender_name = sender["name"] if sender else "Родственник"
        
        await context.bot.send_message(
            target_id,
            f"📨 *Сообщение от {sender_name}*\n\n{message}",
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ Сообщение отправлено!", reply_markup=family_menu)
        
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом!", reply_markup=family_menu)

async def help_command(update: Update, context):
    await update.message.reply_text(
        "🤖 *Команды бота:*\n\n"
        "*/start* — начать заново\n"
        "*/help* — эта справка\n"
        "*/weather* — погода\n"
        "*/add_reminder* — добавить напоминание\n"
        "*/reminders* — список напоминаний\n"
        "*/events* — события\n"
        "*/games* — игры\n"
        "*/nostalgia* — ностальгия\n"
        "*/courses* — курсы\n"
        "*/achievements* — достижения\n"
        "*/family* — семейное меню\n"
        "*/add_relative* — добавить родственника\n"
        "*/id* — написать родственнику\n"
        "*/sos* — экстренная помощь\n\n"
        "Просто пишите — я отвечу! 💬",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def family_command(update: Update, context):
    await update.message.reply_text("👨‍👩‍👧 *Семейное меню:*", parse_mode="Markdown", reply_markup=family_menu)

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

async def sos_command(update: Update, context):
    user_id = update.effective_user.id
    log_activity(user_id, "sos")
    
    user = get_user(user_id)
    user_name = user["name"] if user else "Родственник"
    
    members = get_family_members(user_id)
    notified = 0
    
    for member in members:
        try:
            await context.bot.send_message(
                member["id"],
                f"🚨 *ВНИМАНИЕ!*\n\n{user_name} нажал(а) кнопку SOS!\n\nПожалуйста, свяжитесь с ним/ней!",
                parse_mode="Markdown"
            )
            notified += 1
        except:
            pass
    
    await update.message.reply_text(
        f"🆘 *Сигнал SOS отправлен!*\n\nУведомлено родственников: {notified}",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def add_reminder_start(update: Update, context):
    await update.message.reply_text("💊 *Когда напоминать?*\nНапишите время ЧЧ:ММ, например 09:00", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return 1

async def add_reminder_time(update: Update, context):
    text = update.message.text
    if not re.match(r'^\d{2}:\d{2}$', text):
        await update.message.reply_text("❌ Формат ЧЧ:ММ, например 14:30")
        return 1
    context.user_data["reminder_time"] = text
    await update.message.reply_text("💊 *Что напоминать?*", parse_mode="Markdown")
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
        await update.message.reply_text("📋 Нет напоминаний.\n/add_reminder — добавить", reply_markup=main_menu)
        return
    lines = ["📋 *Ваши напоминания:*"]
    for r in reminders:
        lines.append(f"• {r['time']} — {r['text']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_menu)

async def events_command(update: Update, context):
    await update.message.reply_text(
        "👥 *Активные события:*\n\n"
        "• 🎨 Рисование — вторник 15:00\n"
        "• 🧘 Зарядка — среда 10:00\n"
        "• 📚 Книжный клуб — пятница 16:00",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def games_command(update: Update, context):
    await update.message.reply_text(
        "🎮 *Игры:*\n\n"
        "• 🃏 Слова\n"
        "• 🧩 Загадки\n"
        "• 🎲 Кости\n\n"
        "Скоро будут доступны!",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def nostalgia_command(update: Update, context):
    await update.message.reply_text(
        "📖 *Ностальгия:*\n\n"
        "• 🎬 Советское кино\n"
        "• 🎵 Старые песни\n"
        "• 📚 Классика литературы",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def courses_command(update: Update, context):
    await update.message.reply_text(
        "📚 *Курсы:*\n\n"
        "• 📱 Компьютерная грамотность\n"
        "• 🎨 Рисование\n"
        "• 🧘 Здоровье",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def achievements_command(update: Update, context):
    user_id = update.effective_user.id
    stats = get_stats(user_id)
    await update.message.reply_text(
        f"🏆 *Достижения:*\n\n"
        f"💬 Диалогов: *{stats['talks']}*\n"
        f"💊 Приёмов лекарств: *{stats['meds']}*\n"
        f"🆘 SOS: *{stats['sos']}*",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def voice_help_command(update: Update, context):
    await update.message.reply_text(
        "🎤 *Голосовой помощник*\n\n"
        "Отправьте голосовое сообщение — я распознаю и отвечу!",
        parse_mode="Markdown", reply_markup=main_menu
    )

async def set_city(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.lower()
    match = re.search(r'(мой город|живу в|город)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', text)
    if match:
        city = match.group(2).strip().capitalize()
        if len(city) > 1:
            user = get_user(user_id) or {}
            save_user(user_id, name=user.get("name"), city=city)
            await update.message.reply_text(f"✅ Запомнила! Город: *{city}*", parse_mode="Markdown", reply_markup=main_menu)

async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text and text[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️", "🌤️", "🎮", "📖"]:
        text = text[1:].strip()
        if not text:
            await update.message.reply_text("Напиши что-нибудь! 😊", reply_markup=main_menu)
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
    if text_lower in ['семья', 'family']:
        await family_command(update, context)
        return
    
    log_activity(user_id, "talk")
    msg = await update.message.reply_text("🤔 Думаю...")
    reply = await ai_chat(text)
    await msg.delete()
    
    if reply:
        await update.message.reply_text(reply, reply_markup=main_menu)
    else:
        await update.message.reply_text(
            "😊 *Я тебя услышал!*\n\n"
            "• *погода* — узнать погоду\n"
            "• *время* — узнать время\n"
            "• *мой город Москва* — запомнить город\n"
            "• /help — все команды",
            parse_mode="Markdown", reply_markup=main_menu
        )

async def handle_voice(update: Update, context):
    await update.message.reply_text(
        "🎤 *Голосовое сообщение получено!*\n\n"
        "Пожалуйста, напишите текстом — я отвечу! 😊",
        parse_mode="Markdown", reply_markup=main_menu
    )

# ==================== ЗАПУСК ====================

def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан!")
        return
    
    init_db()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Conversation для выбора роли
    start_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, role_choice)]},
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(start_conv)
    
    # Команды
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("family", family_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(CommandHandler("reminders", reminders_list))
    app.add_handler(CommandHandler("events", events_command))
    app.add_handler(CommandHandler("games", games_command))
    app.add_handler(CommandHandler("nostalgia", nostalgia_command))
    app.add_handler(CommandHandler("courses", courses_command))
    app.add_handler(CommandHandler("achievements", achievements_command))
    app.add_handler(CommandHandler("voice_help", voice_help_command))
    app.add_handler(CommandHandler("sos", sos_command))
    app.add_handler(CommandHandler("id", send_to_relative))
    
    # Добавление родственника
    add_relative_conv = ConversationHandler(
        entry_points=[CommandHandler("add_relative", add_relative_start)],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_relative_id)]},
        fallbacks=[]
    )
    app.add_handler(add_relative_conv)
    
    # Напоминания
    reminder_conv = ConversationHandler(
        entry_points=[CommandHandler("add_reminder", add_reminder_start)],
        states={1: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_time)],
                2: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_text)]},
        fallbacks=[]
    )
    app.add_handler(reminder_conv)
    
    # Обработчики
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Regex("^(👵 Мои бабушки/дедушки|👶 Мои внуки/дети|➕ Добавить родственника|📊 Статистика семьи|🔙 Назад в меню)$"), family_menu_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
