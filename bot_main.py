from __future__ import annotations

import os
import logging
import sys
import threading
import asyncio
import re
import json
import random
import io
from enum import Enum, auto
from typing import Final
from datetime import time, date, timedelta
from flask import Flask

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    JobQueue,
    filters,
)
from telegram.request import HTTPXRequest
from telegram.error import NetworkError, TimedOut

from bot_config import get_settings
from ai_stubs import generate_companion_reply
from storage import (
    init_db,
    upsert_user,
    list_reminders,
    add_reminder,
    log_activity,
    get_activity_summary,
    add_relative_link,
    get_relatives_for_senior,
    init_chat_history_table,
    save_message,
    get_chat_history,
    clear_chat_history,
    init_family_feed_table,
    get_family_id_for_user,
    add_to_family_feed,
    get_family_feed,
    init_calendar_table,
    add_event,
    get_events_for_user,
    get_event_by_id,
    delete_event,
    get_events_by_date,
    init_games_table,
    save_game_state,
    get_game_state,
    clear_game_state,
    get_user_stats,
    get_family_stats,
    get_reminder_completion_rate,
    generate_health_report,
    generate_family_report,
    get_user,
)
from weather import get_weather_summary
from features_stub import (
    social_events_overview,
    social_companions_info,
    social_volunteers_info,
    health_extra_info,
    home_helper_info,
    games_menu_text,
    nostalgia_menu_text,
    courses_menu_text,
    achievements_text,
    voice_interface_info,
    analytics_info_text,
)

# ---------- Голосовые сообщения ----------
import speech_recognition as sr
from pydub import AudioSegment


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ==================== FLASK ДЛЯ HEALTH CHECKS ====================
flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health_check():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False)


# ==================== КОНСТАНТЫ ====================
class Role(Enum):
    SENIOR = "senior"
    RELATIVE = "relative"

class OnboardingState(Enum):
    CHOOSING_ROLE = auto()
    SENIOR_NAME = auto()
    SENIOR_AGE = auto()
    SENIOR_CITY = auto()
    SENIOR_INTERESTS = auto()
    RELATIVE_CODE = auto()

class MedsState(Enum):
    ASK_TIME = auto()
    ASK_TEXT = auto()

MAIN_MENU_KEYBOARD: Final = ReplyKeyboardMarkup(
    [
        ["💬 Поговорить", "📅 Напоминания"],
        ["👥 События", "🆘 ПОМОЩЬ"],
        ["👨‍👩‍👧 Семья", "⚙️ Настройки"],
        ["🎮 Игры", "🌤️ Погода"],
    ],
    resize_keyboard=True,
)


# ==================== ОНБОРДИНГ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    text = (
        "Здравствуйте! Я бот-компаньон «Семья» 🏡\n\n"
        "Давайте познакомимся.\n"
        "Кто вы?\n\n"
        "➤ Я пожилой пользователь\n"
        "➤ Я родственник/опекун"
    )
    keyboard = [["Я пользователь", "Я родственник"]]
    await update.message.reply_text(
        text,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return OnboardingState.CHOOSING_ROLE.value

async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip().lower()
    if "родствен" in text:
        context.user_data["role"] = Role.RELATIVE.value
        await update.message.reply_text(
            "Хорошо! Вы родственник.\n"
            "Пожалуйста, введите код привязки, который мы выдадим вашему близкому человеку.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return OnboardingState.RELATIVE_CODE.value
    context.user_data["role"] = Role.SENIOR.value
    await update.message.reply_text(
        "Рада знакомству! 🌷 Как вас зовут?\n\n"
        "Напишите, пожалуйста, как к вам обращаться.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return OnboardingState.SENIOR_NAME.value

async def senior_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = (update.message.text or "").strip()
    await update.message.reply_text(
        f"Очень приятно, {context.user_data['name']}!\n\n"
        "Подскажите, пожалуйста, сколько вам лет?",
    )
    return OnboardingState.SENIOR_AGE.value

async def senior_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text("Пожалуйста, введите число (например, 72).")
        return OnboardingState.SENIOR_AGE.value
    context.user_data["age"] = int(text)
    await update.message.reply_text("Спасибо!\n\nВ каком городе вы живёте?")
    return OnboardingState.SENIOR_CITY.value

async def senior_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["city"] = (update.message.text or "").strip()
    await update.message.reply_text(
        "Отлично!\n\nРасскажите, чем вы любите заниматься? "
        "Например: сад, книги, фильмы, вязание, шахматы…",
    )
    return OnboardingState.SENIOR_INTERESTS.value

async def senior_interests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["interests"] = (update.message.text or "").strip()
    user = update.effective_user
    telegram_id = user.id if user else 0
    role = context.user_data.get("role", Role.SENIOR.value)
    name = context.user_data.get("name")
    age = context.user_data.get("age")
    city = context.user_data.get("city")
    interests = context.user_data.get("interests")
    upsert_user(telegram_id, role, name, age, city, interests)
    name_for_text = name or "друг"
    await update.message.reply_text(
        f"Спасибо, {name_for_text}! Я всё запомнила.\n\n"
        "Теперь вы можете пользоваться мной как компаньоном.\n"
        "Если что-то пойдёт не так, вы всегда можете написать мне простым текстом.\n\n"
        "Вот главное меню:",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    return ConversationHandler.END

async def relative_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = (update.message.text or "").strip()
    context.user_data["relative_code"] = code
    user = update.effective_user
    telegram_id = user.id if user else 0
    upsert_user(telegram_id, Role.RELATIVE.value, name=user.first_name if user else None)
    await update.message.reply_text(
        "Спасибо! На этом этапе мы считаем, что код принят.\n"
        "Позже здесь появится панель мониторинга для ваших близких.\n\n"
        "Пока что вы можете видеть тестовое меню:",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    return ConversationHandler.END


# ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ====================
async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info(f"🖲️ Нажата кнопка: {text}")
    if text == "💬 Поговорить":
        await handle_talk(update, context)
    elif text == "📅 Напоминания":
        await handle_reminders(update, context)
    elif text == "👥 События":
        await handle_events(update, context)
    elif text == "🆘 ПОМОЩЬ":
        await handle_sos(update, context)
    elif text == "👨‍👩‍👧 Семья":
        await handle_family(update, context)
    elif text == "⚙️ Настройки":
        await handle_settings(update, context)
    elif text == "🎮 Игры":
        await games_menu(update, context)
    elif text == "🌤️ Погода":
        await weather_command(update, context)
    else:
        await handle_talk(update, context)

async def handle_talk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id if user else 0
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    last_text = (update.message.text or "").strip()

    if user_id:
        save_message(user_id, "user", last_text)

    if user:
        log_activity(user.id, "talk")

    reply = await generate_companion_reply(last_text, name=name, user_id=user_id)
    await update.message.reply_text(reply)

    if user_id and reply:
        save_message(user_id, "assistant", reply)

async def handle_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    telegram_id = user.id if user else 0
    reminders = list_reminders(telegram_id)
    if not reminders:
        await update.message.reply_text(
            "У вас пока нет напоминаний.\n\n"
            "Я могу каждый день напоминать о лекарствах.\n"
            "Отправьте команду /add_meds, чтобы добавить напоминание.",
        )
        return
    lines = ["Ваши напоминания:"]
    for r in reminders:
        status = "✅" if r["enabled"] else "⏸"
        lines.append(f"{status} {r['time_local']} — {r['text']}")
    lines.append("\nЧтобы добавить новое напоминание о лекарствах, отправьте /add_meds.")
    await update.message.reply_text("\n".join(lines))

async def handle_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(social_events_overview())
    await update.message.reply_text(
        "Дополнительно вы можете использовать команды:\n"
        "• /companions — поиск компаньонов (описание)\n"
        "• /volunteers — волонтёрская помощь (описание)",
    )

async def notify_family_members(family_id: int, exclude_user_id: int, bot, notification: str):
    import sqlite3
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT relative_id FROM relatives WHERE senior_id = ?", (family_id,))
    relatives = [row[0] for row in cursor.fetchall()]
    if family_id != exclude_user_id:
        relatives.append(family_id)
    conn.close()
    for member_id in relatives:
        try:
            await bot.send_message(member_id, notification, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление {member_id}: {e}")

async def handle_sos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        log_activity(user.id, "sos")
    await update.message.reply_text(
        "Вы нажали SOS. Я зафиксировала это событие и, по возможности, уведомлю ваших близких.",
    )
    if user:
        user_name = context.user_data.get("name") or user.first_name or "Родственник"
        relatives = get_relatives_for_senior(user.id)
        for rel_id in relatives:
            try:
                await context.bot.send_message(
                    chat_id=rel_id,
                    text=(
                        "Внимание.\n\n"
                        f"Ваш близкий (Telegram ID {user.id}) нажал кнопку SOS в боте «Семья».\n"
                        "Пожалуйста, свяжитесь с ним как можно скорее."
                    ),
                )
            except Exception as e:
                logger.warning("Failed to notify relative %s about SOS: %s", rel_id, e)
        family_id = get_family_id_for_user(user.id)
        if family_id:
            add_to_family_feed(family_id, user.id, user_name, "Нажата кнопка SOS!", "sos")
            notification = f"🚨 *{user_name}* нажал(а) SOS! Пожалуйста, проверьте семейную ленту."
            await notify_family_members(family_id, user.id, context.bot, notification)

async def handle_family(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    telegram_id = user.id if user else 0
    summary = get_activity_summary(telegram_id)
    talk = summary.get("talk", 0)
    meds_done = summary.get("reminder_done", 0)
    sos = summary.get("sos", 0)
    lines = ["Дневник активности за последние 24 часа:"]
    lines.append(f"💬 Разговоры с ботом: {talk}")
    lines.append(f"💊 Выполненные напоминания (отметка «Принял(а)»): {meds_done}")
    lines.append(f"🆘 Нажатий SOS: {sos}")
    lines.append("\nПозже здесь появится общий семейный чат и подробная статистика для родственников.")
    await update.message.reply_text("\n".join(lines))

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Здесь со временем появятся настройки: таймзона, частота напоминаний, "
        "скорость речи и другие параметры.\n\n"
        "Полезные команды:\n"
        "• /enable_checkin — ежедневно спрашивать «Как дела?»\n"
        "• /disable_checkin — отключить ежедневный вопрос\n"
        "• /voice_help — рассказ о голосовом интерфейсе\n"
        "• /clear_history — очистить историю диалогов\n"
        "• /family_send — отправить сообщение в семейный чат\n"
        "• /family_feed — показать семейную ленту\n"
        "• /add_event — добавить событие в календарь\n"
        "• /events_list — список событий\n"
        "• /delete_event — удалить событие\n"
        "• /health_report — мой отчёт о здоровье\n"
        "• /family_report — сводный отчёт по семье\n"
        "• /member_stats — статистика члена семьи\n"
        "• /games — игры и викторины",
    )

async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_talk(update, context)


# ---------- Напоминания о лекарствах ----------
async def add_meds_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Когда напоминать о приёме лекарств?\n"
        "Напишите время в формате ЧЧ:ММ, например 09:00 или 21:30.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return MedsState.ASK_TIME.value

async def add_meds_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await update.message.reply_text("Пожалуйста, введите время в формате ЧЧ:ММ, например 08:30.")
        return MedsState.ASK_TIME.value
    h, m = map(int, parts)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        await update.message.reply_text("Часы от 00 до 23, минуты от 00 до 59. Попробуйте ещё раз.")
        return MedsState.ASK_TIME.value
    context.user_data["meds_time"] = f"{h:02d}:{m:02d}"
    await update.message.reply_text(
        "Что мне напоминать?\n"
        "Например: «Принять таблетку от давления».",
    )
    return MedsState.ASK_TEXT.value

async def meds_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    text = job.data.get("text", "Пора принять лекарство.")
    try:
        await context.bot.send_message(chat_id=chat_id, text=f"💊 Напоминание: {text}")
        log_activity(chat_id, "reminder_done")
    except Exception as e:
        logger.warning("Failed to send meds reminder to %s: %s", chat_id, e)

async def add_meds_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    telegram_id = user.id if user else 0
    meds_time = context.user_data.get("meds_time", "09:00")
    text = (update.message.text or "").strip() or "Принять лекарство"
    add_reminder(telegram_id, "meds", text, meds_time)
    job_queue: JobQueue = context.job_queue
    try:
        hours, minutes = map(int, meds_time.split(":"))
        job_queue.run_daily(
            meds_reminder_job,
            time=time(hour=hours, minute=minutes),
            chat_id=telegram_id,
            name=f"meds-{telegram_id}-{meds_time}",
            data={"text": text},
        )
    except Exception as e:
        logger.warning("Failed to schedule meds reminder for %s at %s: %s", telegram_id, meds_time, e)
    await update.message.reply_text(
        f"Хорошо, я буду каждый день в {meds_time} напоминать вам: «{text}».\n\n"
        "Вы всегда можете посмотреть список напоминаний через кнопку «📅 Напоминания».",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    return ConversationHandler.END

async def meds_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Настройка напоминания отменена.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    return ConversationHandler.END


# ---------- Ежедневная проверка «Как дела?» ----------
async def daily_checkin(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Как вы себя сегодня чувствуете? 🌷\n"
            "Если всё в порядке, можете просто написать мне пару слов.",
        )
    except Exception as e:
        logger.warning("Failed to send daily check-in to %s: %s", chat_id, e)

async def enable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    job_queue: JobQueue = context.job_queue
    for job in job_queue.get_jobs_by_name(f"checkin-{chat_id}"):
        job.schedule_removal()
    job_queue.run_daily(
        daily_checkin,
        time=time(hour=10, minute=0),
        chat_id=chat_id,
        name=f"checkin-{chat_id}",
    )
    await update.message.reply_text(
        "Хорошо, я буду каждый день в 10:00 спрашивать, как у вас дела. 🌞",
    )

async def disable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    job_queue: JobQueue = context.job_queue
    for job in job_queue.get_jobs_by_name(f"checkin-{chat_id}"):
        job.schedule_removal()
    await update.message.reply_text("Ежедневный вопрос «Как дела?» отключен.")


# ---------- Привязка родственника ----------
async def add_relative_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not context.args:
        await update.message.reply_text(
            "Использование: /add_relative <Telegram ID пожилого пользователя>.\n"
            "Например: /add_relative 123456789",
        )
        return
    try:
        senior_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом. Попробуйте ещё раз.")
        return
    if not user:
        await update.message.reply_text("Не удалось определить ваш Telegram ID.")
        return
    add_relative_link(senior_id, user.id)
    await update.message.reply_text(
        f"Готово. Я связала вас с пользователем с Telegram ID {senior_id}.\n"
        "Теперь при нажатии SOS ему я постараюсь отправить вам уведомление.\n"
        "Вы также можете отправлять сообщения в семейный чат через /family_send",
    )


# ---------- Семейная лента (общий чат) ----------
async def family_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = context.user_data.get("name") or update.effective_user.first_name or "Член семьи"
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("❌ Вы не привязаны ни к одной семье. Используйте /add_relative.")
        return
    
    if not context.args:
        await update.message.reply_text("📝 Использование: /family_send <текст сообщения>")
        return
    message_text = " ".join(context.args)
    
    add_to_family_feed(family_id, user_id, user_name, message_text, "text")
    
    notification = f"📢 *{user_name}* пишет в семейный чат:\n\n{message_text}"
    await notify_family_members(family_id, user_id, context.bot, notification)
    
    await update.message.reply_text("✅ Сообщение отправлено в семейную ленту!")

async def family_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        family_id = get_family_id_for_user(user_id)
    except Exception as e:
        logger.error(f"Ошибка получения family_id: {e}")
        await update.message.reply_text("❌ Ошибка базы данных. Попробуйте позже.")
        return
    if not family_id:
        await update.message.reply_text("❌ Вы не привязаны ни к одной семье.")
        return
    
    feed = get_family_feed(family_id, limit=15)
    if not feed:
        await update.message.reply_text("📭 В семейной ленте пока нет сообщений.")
        return
    
    lines = ["📋 *Семейная лента:*\n"]
    for entry in feed:
        time_str = str(entry["created_at"])[:16].replace("-", ".").replace("T", " ")
        lines.append(f"👤 *{entry['author_name']}* ({time_str}):\n{entry['message']}\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------- Календарь событий ----------
async def add_event_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 *Добавление события*\n\n"
        "Введите дату в формате ГГГГ-ММ-ДД (например, 2025-12-31):",
        parse_mode="Markdown"
    )
    return 1

async def add_event_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_str = update.message.text.strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        await update.message.reply_text("❌ Неверный формат. Используйте ГГГГ-ММ-ДД, например 2025-12-31.")
        return 1
    context.user_data["event_date"] = date_str
    await update.message.reply_text("Введите время (опционально) в формате ЧЧ:ММ или '-' пропустить:")
    return 2

async def add_event_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text.strip()
    if time_str == "-":
        context.user_data["event_time"] = None
    elif not re.match(r'^\d{2}:\d{2}$', time_str):
        await update.message.reply_text("❌ Неверный формат времени. Используйте ЧЧ:ММ или '-' пропустить.")
        return 2
    else:
        context.user_data["event_time"] = time_str
    await update.message.reply_text("Введите название события (обязательно):")
    return 3

async def add_event_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("Название не может быть пустым. Введите название:")
        return 3
    context.user_data["event_title"] = title
    await update.message.reply_text("Введите описание (необязательно, можно '-' пропустить):")
    return 4

async def add_event_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    context.user_data["event_description"] = desc if desc != "-" else None
    await update.message.reply_text("Выберите тип события:\n1 - День рождения\n2 - Праздник\n3 - Встреча\n4 - Другое")
    return 5

async def add_event_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    type_map = {"1": "birthday", "2": "holiday", "3": "meeting", "4": "other"}
    choice = update.message.text.strip()
    if choice not in type_map:
        await update.message.reply_text("Пожалуйста, выберите 1, 2, 3 или 4.")
        return 5
    context.user_data["event_type"] = type_map[choice]
    await update.message.reply_text("За сколько дней напомнить? (по умолчанию 1, введите число):")
    return 6

async def add_event_remind_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days_str = update.message.text.strip()
    if not days_str.isdigit():
        days = 1
    else:
        days = int(days_str)
    user_id = update.effective_user.id
    add_event(
        user_id=user_id,
        event_date=context.user_data["event_date"],
        title=context.user_data["event_title"],
        description=context.user_data.get("event_description"),
        event_time=context.user_data.get("event_time"),
        event_type=context.user_data.get("event_type", "other"),
        remind_before_days=days
    )
    await update.message.reply_text(
        f"✅ Событие добавлено!\n\n📅 {context.user_data['event_date']}\n"
        f"📌 {context.user_data['event_title']}\n"
        f"🔔 Напомню за {days} дн.",
        reply_markup=MAIN_MENU_KEYBOARD
    )
    context.user_data.clear()
    return -1

async def events_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today = date.today().isoformat()
    events = get_events_for_user(user_id, from_date=today, limit=20)
    if not events:
        await update.message.reply_text("📭 У вас нет предстоящих событий.")
        return
    lines = ["📅 *Ваши ближайшие события:*\n"]
    for ev in events:
        time_str = f" {ev['time']}" if ev['time'] else ""
        lines.append(f"• {ev['date']}{time_str} – *{ev['title']}*")
        if ev['description']:
            lines.append(f"  _{ev['description']}_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def delete_event_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажите ID события: /delete_event <id>")
        return
    try:
        event_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return
    user_id = update.effective_user.id
    success = delete_event(event_id, user_id)
    if success:
        await update.message.reply_text(f"✅ Событие {event_id} удалено.")
    else:
        await update.message.reply_text("❌ Событие не найдено или у вас нет прав.")


# ---------- Аналитика и отчёты ----------
async def health_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
        if days > 30:
            days = 30
    report = generate_health_report(user_id, days)
    await update.message.reply_text(report, parse_mode="Markdown")

async def family_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("❌ Вы не привязаны ни к одной семье.")
        return
    
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
        if days > 30:
            days = 30
    
    report = generate_family_report(family_id, days)
    await update.message.reply_text(report, parse_mode="Markdown")

async def member_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("❌ Вы не привязаны ни к одной семье.")
        return
    
    if not context.args:
        await update.message.reply_text("📝 Использование: /member_stats <Telegram ID> [дни]")
        return
    
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return
    
    import sqlite3
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM relatives WHERE senior_id = ? AND relative_id = ?", (family_id, target_id))
    is_relative = cursor.fetchone() is not None
    conn.close()
    
    if target_id != family_id and not is_relative:
        await update.message.reply_text("❌ Этот пользователь не является членом вашей семьи.")
        return
    
    days = 7
    if len(context.args) > 1 and context.args[1].isdigit():
        days = int(context.args[1])
        if days > 30:
            days = 30
    
    stats = get_user_stats(target_id, days)
    user_info = get_user(target_id)
    name = user_info["name"] if user_info else f"User_{target_id}"
    
    report = f"📊 *Статистика пользователя {name}* (ID: {target_id})\n"
    report += f"📅 За последние {days} дней:\n\n"
    report += f"💬 Разговоров: {stats['talks']}\n"
    report += f"💊 Приёмов лекарств: {stats['reminders_done']}\n"
    report += f"🆘 SOS: {stats['sos']}\n"
    if stats['voice'] > 0:
        report += f"🎤 Голосовых: {stats['voice']}\n"
    report += f"\n🏆 *Всего активностей:* {stats['total']}"
    
    await update.message.reply_text(report, parse_mode="Markdown")


# ---------- Игры и викторины ----------
RIDDLES = [
    ("Висит груша, нельзя скушать. Что это?", "лампочка"),
    ("Не лает, не кусает, а в дом не пускает.", "замок"),
    ("Без окон, без дверей, полна горница людей.", "огурец"),
    ("Что можно приготовить, но нельзя съесть?", "урок"),
    ("Чем больше из неё берёшь, тем больше она становится.", "яма"),
    ("Кто говорит на всех языках?", "эхо"),
    ("Зимой и летом одним цветом.", "ёлка"),
    ("Сидит дед, в сто шуб одет. Кто его раздевает, тот слёзы проливает.", "лук"),
    ("Что вниз головой растёт?", "сосулька"),
    ("Не вода, не суша – на лодке не уплывёшь и ногами не пройдёшь.", "болото"),
]

TRUTH_OR_LIE = [
    ("Пингвины умеют летать.", False),
    ("Верблюды хранят воду в горбах.", False),
    ("Страусы прячут голову в песок.", False),
    ("Лимон содержит больше сахара, чем клубника.", True),
    ("Язык хамелеона длиннее его тела.", True),
    ("Банан – это ягода.", True),
    ("У осьминога три сердца.", True),
    ("Шоколад ядовит для собак.", True),
    ("Улитки могут спать три года.", True),
    ("Стекло – это жидкое вещество.", False),
]

async def games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["🔮 Загадка", "📖 Слова"],
        ["✅ Правда или ложь", "❌ Выйти из игры"]
    ]
    await update.message.reply_text(
        "🎮 *Игры и викторины*\n\nВыберите игру:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )

async def play_riddle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    riddle = random.choice(RIDDLES)
    save_game_state(user_id, "riddle", json.dumps({"question": riddle[0], "answer": riddle[1]}))
    await update.message.reply_text(
        f"🔮 *Загадка:*\n\n{riddle[0]}\n\nНапишите свой ответ:",
        parse_mode="Markdown"
    )

async def play_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_game_state(user_id, "words", json.dumps({"last_letter": None, "used_words": []}))
    await update.message.reply_text(
        "📖 *Игра «Слова»*\n\n"
        "Правила: называете слово, следующий игрок называет слово на последнюю букву предыдущего.\n"
        "Вы начинаете! Напишите любое слово (существительное, именительный падеж).",
        parse_mode="Markdown"
    )

async def play_truth_or_lie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    question, answer = random.choice(TRUTH_OR_LIE)
    save_game_state(user_id, "truth_or_lie", json.dumps({"question": question, "answer": answer}))
    await update.message.reply_text(
        f"✅ *Правда или ложь?*\n\n{question}\n\nОтправьте «правда» или «ложь»:",
        parse_mode="Markdown"
    )

async def exit_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    clear_game_state(user_id)
    await update.message.reply_text(
        "❌ Вы вышли из игры. Возвращайтесь ещё!",
        reply_markup=MAIN_MENU_KEYBOARD
    )

def find_word_on_letter(letter: str, used_words: set) -> str:
    words_db = ["апельсин", "банан", "вишня", "груша", "дыня", "ежевика", "жёлудь", "земляника", "ирис", "йогурт",
                "клубника", "лимон", "малина", "ноутбук", "обезьяна", "помидор", "рис", "самолёт", "телефон", "улитка",
                "фонарь", "хлеб", "цветок", "чайник", "шапка", "щёголь", "эскимо", "юбка", "яблоко"]
    for word in words_db:
        if word[0] == letter and word not in used_words:
            return word
    return None

async def handle_game_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_game_state(user_id)
    if not state:
        return
    game_name = state["game_name"]
    game_data = json.loads(state["game_data"])
    answer = update.message.text.strip().lower()
    
    if game_name == "riddle":
        correct_answer = game_data["answer"]
        if answer == correct_answer or answer in correct_answer:
            await update.message.reply_text("🎉 Правильно! Отличная работа!\n\nЧтобы сыграть ещё раз, нажмите /games", reply_markup=MAIN_MENU_KEYBOARD)
        else:
            await update.message.reply_text(f"❌ Неправильно! Правильный ответ: {correct_answer}\n\nСыграйте ещё раз: /games", reply_markup=MAIN_MENU_KEYBOARD)
        clear_game_state(user_id)
    
    elif game_name == "words":
        last_letter = game_data.get("last_letter")
        used_words = set(game_data.get("used_words", []))
        
        if answer in used_words:
            await update.message.reply_text(f"❌ Слово «{answer}» уже было! Вы проиграли. Начните новую игру: /games")
            clear_game_state(user_id)
            return
        
        if last_letter and answer[0] != last_letter:
            await update.message.reply_text(f"❌ Слово должно начинаться на букву «{last_letter}»! Вы проиграли. Начните новую игру: /games")
            clear_game_state(user_id)
            return
        
        if len(answer) < 2:
            await update.message.reply_text(f"❌ Слишком короткое слово! Вы проиграли. Начните новую игру: /games")
            clear_game_state(user_id)
            return
        
        used_words.add(answer)
        last_letter = answer[-1]
        save_game_state(user_id, "words", json.dumps({"last_letter": last_letter, "used_words": list(used_words)}))
        
        bot_word = find_word_on_letter(last_letter, used_words)
        if bot_word:
            used_words.add(bot_word)
            new_last_letter = bot_word[-1]
            save_game_state(user_id, "words", json.dumps({"last_letter": new_last_letter, "used_words": list(used_words)}))
            await update.message.reply_text(f"🤖 Моё слово: {bot_word}\nТеперь ваша очередь на букву «{new_last_letter}».")
        else:
            await update.message.reply_text(f"🎉 Я не могу найти слово на букву «{last_letter}»! Вы победили! Поздравляю!\n\nНачать новую игру: /games")
            clear_game_state(user_id)
    
    elif game_name == "truth_or_lie":
        is_true = answer in ["правда", "верно", "да", "true", "truth"]
        is_false = answer in ["ложь", "неправда", "нет", "false", "lie"]
        
        if not (is_true or is_false):
            await update.message.reply_text("Пожалуйста, ответьте «правда» или «ложь».")
            return
        
        correct = game_data["answer"]
        if (is_true and correct) or (is_false and not correct):
            await update.message.reply_text("🎉 Правильно! Отличная эрудиция!\n\nСыграть ещё: /games", reply_markup=MAIN_MENU_KEYBOARD)
        else:
            await update.message.reply_text(f"❌ Неправильно! {game_data['question']} – это {'правда' if correct else 'ложь'}.\n\nСыграть ещё: /games", reply_markup=MAIN_MENU_KEYBOARD)
        clear_game_state(user_id)


# ---------- Голосовые сообщения ----------
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user else 0
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    
    processing_msg = await update.message.reply_text(
        "🎤 Слушаю ваше голосовое сообщение...\n\nЭто может занять несколько секунд."
    )
    
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        
        # Конвертация OGG -> WAV
        audio = AudioSegment.from_ogg(io.BytesIO(audio_bytes))
        audio = audio.set_channels(1).set_frame_rate(16000)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio_data = recognizer.record(source)
        
        recognized_text = None
        try:
            recognized_text = recognizer.recognize_google(audio_data, language="ru-RU")
        except sr.UnknownValueError:
            try:
                recognized_text = recognizer.recognize_google(audio_data, language="en-US")
            except sr.UnknownValueError:
                pass
        
        if not recognized_text:
            await processing_msg.edit_text(
                "😔 Не удалось распознать голосовое сообщение.\n\n"
                "Попробуйте:\n"
                "• Говорить чётче и медленнее\n"
                "• Уменьшить фоновый шум\n"
                "• Отправить сообщение короче (3-5 секунд)\n\n"
                "Или просто напишите текстом! 💬",
                reply_markup=MAIN_MENU_KEYBOARD
            )
            return
        
        await processing_msg.edit_text(
            f"📝 Вы сказали: *\"{recognized_text}\"*\n\n🤔 Думаю над ответом...",
            parse_mode="Markdown"
        )
        
        reply = await generate_companion_reply(recognized_text, name=name, user_id=user_id)
        
        await processing_msg.delete()
        await update.message.reply_text(reply, reply_markup=MAIN_MENU_KEYBOARD)
        
        if user:
            log_activity(user.id, "voice")
            
    except Exception as e:
        logger.error(f"Voice handling error: {e}")
        await processing_msg.edit_text(
            "❌ Произошла ошибка при обработке голосового сообщения.\n\n"
            "Пожалуйста, попробуйте ещё раз или напишите текстом.",
            reply_markup=MAIN_MENU_KEYBOARD
        )


# ---------- Дополнительные команды ----------
async def companions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(social_companions_info())

async def volunteers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(social_volunteers_info())

async def health_extra_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(health_extra_info())

async def helper_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(home_helper_info())

async def nostalgia_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(nostalgia_menu_text())

async def courses_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(courses_menu_text())

async def achievements_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(achievements_text())

async def admin_analytics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(analytics_info_text())

async def voice_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(voice_interface_info())

async def clear_history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    clear_chat_history(user_id)
    await update.message.reply_text("🧹 История диалогов очищена!", reply_markup=MAIN_MENU_KEYBOARD)


# ---------- Навигация ----------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *Бот-компаньон «Семья»*\n\n"
        "Основные команды:\n"
        "• /start — начать заново\n"
        "• /menu — главное меню\n"
        "• /help — эта справка\n\n"
        "💬 *Общение:*\n"
        "• Просто напишите текст – я отвечу через нейросеть\n"
        "• 🎤 Отправьте голосовое сообщение – я распознаю и отвечу\n\n"
        "📅 *Напоминания:*\n"
        "• /add_meds — добавить напоминание о лекарствах\n"
        "• /enable_checkin — ежедневный опрос «Как дела?»\n"
        "• /disable_checkin — отключить опрос\n\n"
        "👨‍👩‍👧 *Семья:*\n"
        "• /add_relative <ID> — привязать родственника\n"
        "• /family_send <текст> — отправить в семейный чат\n"
        "• /family_feed — показать семейную ленту\n"
        "• /sos — экстренная помощь\n\n"
        "📊 *Аналитика:*\n"
        "• /health_report [дни] — мой отчёт о здоровье\n"
        "• /family_report [дни] — сводный отчёт по семье\n"
        "• /member_stats <ID> [дни] — статистика члена семьи\n\n"
        "📅 *Календарь:*\n"
        "• /add_event — добавить событие\n"
        "• /events_list — список событий\n"
        "• /delete_event <id> — удалить событие\n\n"
        "🎮 *Игры:*\n"
        "• /games — меню игр (загадки, слова, правда/ложь)\n\n"
        "🌤️ *Погода:*\n"
        "• /weather — погода (нужно указать город)\n"
        "• Напишите «мой город Москва» – запомню\n\n"
        "🆘 *Помощь:*\n"
        "• /companions — поиск компаньонов\n"
        "• /volunteers — волонтёрская помощь\n"
        "• /health_extra — советы по здоровью\n"
        "• /helper — помощь по дому\n"
        "• /nostalgia — ностальгия\n"
        "• /courses — курсы\n"
        "• /achievements — достижения\n"
        "• /admin_stats — аналитика (для админов)",
        parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Вот ваше главное меню.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )


# ---------- Погода ----------
async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    city = context.user_data.get("city")
    if not city:
        await update.message.reply_text(
            f"{name}, я пока не знаю ваш город.\n"
            "Пожалуйста, напишите мне: «Я живу в <город>», и мы добавим это в профиле.",
        )
        return
    summary = await get_weather_summary(city)
    if not summary:
        await update.message.reply_text(
            "Не получилось получить прогноз погоды сейчас. Попробуйте чуть позже.",
        )
        return
    await update.message.reply_text(
        f"Доброе утро, {name}!\n\n{summary}\n\n"
        "Пожалуйста, будьте осторожны и одевайтесь по погоде.",
    )


# ==================== ПОСТРОЕНИЕ ПРИЛОЖЕНИЯ ====================
def build_application():
    settings = get_settings()
    init_db()
    init_chat_history_table()
    init_family_feed_table()
    init_calendar_table()
    init_games_table()

    builder = ApplicationBuilder().token(settings.telegram_token)
    request = HTTPXRequest(
        connect_timeout=settings.telegram_connect_timeout,
        read_timeout=settings.telegram_read_timeout,
        write_timeout=settings.telegram_read_timeout,
        proxy=settings.telegram_proxy,
    )
    builder = builder.request(request)
    application = builder.build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            OnboardingState.CHOOSING_ROLE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_role)],
            OnboardingState.SENIOR_NAME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, senior_name)],
            OnboardingState.SENIOR_AGE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, senior_age)],
            OnboardingState.SENIOR_CITY.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, senior_city)],
            OnboardingState.SENIOR_INTERESTS.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, senior_interests)],
            OnboardingState.RELATIVE_CODE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, relative_code)],
        },
        fallbacks=[],
    )
    application.add_handler(conv_handler)

    meds_conv = ConversationHandler(
        entry_points=[CommandHandler("add_meds", add_meds_start)],
        states={
            MedsState.ASK_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_time)],
            MedsState.ASK_TEXT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_text)],
        },
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(meds_conv)

    event_conv = ConversationHandler(
        entry_points=[CommandHandler("add_event", add_event_start)],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_date)],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_time)],
            3: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_title)],
            4: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_description)],
            5: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_type)],
            6: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_remind_days)],
        },
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(event_conv)

    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("enable_checkin", enable_checkin))
    application.add_handler(CommandHandler("disable_checkin", disable_checkin))
    application.add_handler(CommandHandler("voice_help", voice_help))
    application.add_handler(CommandHandler("add_relative", add_relative_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("menu", menu_cmd))
    application.add_handler(CommandHandler("clear_history", clear_history_cmd))

    application.add_handler(CommandHandler("family_send", family_send))
    application.add_handler(CommandHandler("family_feed", family_feed))

    application.add_handler(CommandHandler("events_list", events_list))
    application.add_handler(CommandHandler("delete_event", delete_event_cmd))

    application.add_handler(CommandHandler("health_report", health_report))
    application.add_handler(CommandHandler("family_report", family_report))
    application.add_handler(CommandHandler("member_stats", member_stats))

    application.add_handler(CommandHandler("games", games_menu))
    application.add_handler(MessageHandler(filters.Regex("^🔮 Загадка$"), play_riddle))
    application.add_handler(MessageHandler(filters.Regex("^📖 Слова$"), play_words))
    application.add_handler(MessageHandler(filters.Regex("^✅ Правда или ложь$"), play_truth_or_lie))
    application.add_handler(MessageHandler(filters.Regex("^❌ Выйти из игры$"), exit_game))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_game_answer), group=1)

    # Голосовые сообщения
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))

    for cmd in [
        companions_cmd, volunteers_cmd, health_extra_cmd, helper_cmd,
        nostalgia_cmd, courses_cmd, achievements_cmd, admin_analytics_cmd
    ]:
        application.add_handler(CommandHandler(cmd.__name__.replace("_cmd", ""), cmd))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_router), group=2)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text), group=3)

    job_queue = application.job_queue
    if job_queue:
        async def daily_event_reminder(context: ContextTypes.DEFAULT_TYPE):
            today = date.today()
            today_events = get_events_by_date(today.isoformat())
            for ev in today_events:
                time_msg = f" в {ev['time']}" if ev['time'] else ""
                await context.bot.send_message(
                    chat_id=ev['user_id'],
                    text=f"🔔 *Напоминание о событии сегодня{time_msg}:*\n{ev['title']}\n{ev['description'] or ''}",
                    parse_mode="Markdown"
                )
            tomorrow = today + timedelta(days=1)
            tomorrow_events = get_events_by_date(tomorrow.isoformat())
            for ev in tomorrow_events:
                if ev['remind_before_days'] >= 1:
                    await context.bot.send_message(
                        chat_id=ev['user_id'],
                        text=f"📅 *Напоминание:* завтра событие «{ev['title']}».",
                        parse_mode="Markdown"
                    )
        job_queue.run_daily(daily_event_reminder, time=time(hour=9, minute=0))

    return application


def run_telegram():
    settings = get_settings()
    logger.info("Starting bot with timezone %s", settings.default_timezone)
    if settings.telegram_proxy:
        safe = settings.telegram_proxy
        if "@" in safe and "://" in safe:
            scheme, rest = safe.split("://", 1)
            if "@" in rest:
                hostpart = rest.split("@", 1)[1]
                safe = f"{scheme}://***@{hostpart}"
        logger.info("Для Telegram используется прокси: %s", safe)
    else:
        logger.warning("Прокси не задан (TELEGRAM_PROXY или HTTPS_PROXY). Если видите TimedOut — включите VPN и укажите локальный HTTP/SOCKS-прокси в .env.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = build_application()

    async def start_bot():
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            await app.updater.stop()
            await app.shutdown()

    try:
        loop.run_until_complete(start_bot())
    except (TimedOut, NetworkError) as exc:
        print(
            "\n──────── Не удаётся достучаться до Telegram (api.telegram.org) ────────\n"
            "Это сетевая проблема: с вашего компьютера соединение до серверов Telegram\n"
            "не устанавливается (блокировка, нет VPN или неверный прокси).\n\n"
            "Что сделать:\n"
            "  1) Включите VPN и в .env укажите локальный прокси из настроек клиента, например:\n"
            "       TELEGRAM_PROXY=http://127.0.0.1:7890\n"
            "     (порт возьмите из настроек вашего VPN — «HTTP proxy», «Mixed port» и т.п.)\n"
            "  2) Для SOCKS5: pip install \"python-telegram-bot[socks]\"\n"
            "       TELEGRAM_PROXY=socks5://127.0.0.1:1080\n"
            "  3) Проверка в терминале:  curl -m 15 -I https://api.telegram.org\n"
            "  4) Надёжно: запустить этого же бота на VPS за пределами блокировки.\n\n"
            f"Ошибка: {exc!r}\n"
            "────────────────────────────────────────────────────────────────────────\n",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def main():
    tg_thread = threading.Thread(target=run_telegram, daemon=True)
    tg_thread.start()
    logger.info("Telegram бот запущен в фоновом потоке")
    run_flask()


if __name__ == "__main__":
    main()
