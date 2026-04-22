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
from typing import Final, Dict, Any
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
from telegram.error import NetworkError, TimedOut, BadRequest

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
    init_media_table,
    save_media,
    get_family_media,
    get_birthdays_for_date,
    get_user_language,
    set_user_language,
    init_health_table,
    add_health_record,
    get_health_records,
    get_health_stats,
    export_chat_history,
    export_health_records,
    export_family_feed,
    init_budget_table,
    add_transaction,
    get_transactions,
    get_budget_summary,
    get_categories,
    get_category_breakdown,
    init_premium_tables,
    is_premium,
    add_premium_user,
    generate_code,
    activate_code,
    get_premium_expiry,
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


# ==================== МНОГОЯЗЫЧНОСТЬ ====================
# ВАЖНО: вставьте сюда ваш полный словарь TEXTS (ru и en) с поддержкой всех ключей.
# Я приведу только новые ключи для бюджета и премиума, а вы дополните своим существующим словарём.
TEXTS = {
    'ru': {
        # ----- Существующие ключи (онбординг, напоминания, SOS и т.д.) вставьте из вашего файла -----
        # ... (ваш словарь) ...
        # Дополнительные ключи для бюджета и премиума:
        'budget_menu': "💰 *Семейный бюджет*\n\nВыберите действие:",
        'budget_add_type': "Выберите тип: 1 - Доход, 2 - Расход",
        'budget_add_category': "Выберите категорию:",
        'budget_add_amount': "Введите сумму (число):",
        'budget_add_date': "Введите дату (ГГГГ-ММ-ДД) или '-' сегодня:",
        'budget_add_desc': "Введите описание (или '-' пропустить):",
        'budget_add_success': "✅ Транзакция добавлена!",
        'budget_stats_text': "💰 *Статистика бюджета*\n\nДоходы: {income:.2f} ₽\nРасходы: {expense:.2f} ₽\nБаланс: {balance:.2f} ₽",
        'budget_breakdown': "\n📊 *Разбивка по категориям (расходы):*",
        'budget_list_empty': "Нет транзакций.",
        'budget_list_header': "📋 *Последние транзакции:*",
        'premium_info': "🌟 *Премиум-доступ*\n\n{status}",
        'premium_active': "✅ У вас активен премиум до {date}.\nСпасибо за поддержку! 🙏",
        'premium_inactive': (
            "🚀 *Платные функции:*\n"
            "• 📊 Расширенная аналитика здоровья (графики, тренды)\n"
            "• 💰 Семейный бюджет (полная статистика, категории)\n"
            "• 📁 Экспорт всех данных (CSV, PDF)\n"
            "• 🎨 Индивидуальные темы оформления\n"
            "• 🔔 Приоритетные напоминания\n\n"
            "💎 *Стоимость:* 300 ₽ за 30 дней\n\n"
            "Для получения премиума свяжитесь с @support или переведите на карту ...\n"
            "После оплаты вы получите код активации.\n\n"
            "Введите код: /activate <код>"
        ),
        'activate_usage': "❌ Введите код: /activate <код>",
        'activate_success': "✅ Премиум активирован! Спасибо за поддержку! 🎉",
        'activate_fail': "❌ Неверный или уже использованный код.",
        'gen_code_usage': "Использование: /gen_code <дни>",
        'gen_code_success': "✅ Сгенерирован код: `{code}`\nДней: {days}",
        'gen_code_error': "❌ Ошибка. Дни должны быть числом.",
        'premium_only': "⭐ Эта функция доступна только в премиум-версии. Используйте /premium",
    },
    'en': {
        # Аналогичные английские тексты (вставьте свои)
    }
}

def get_text(lang: str, key: str, **kwargs) -> str:
    text = TEXTS.get(lang, TEXTS['ru']).get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text

def get_main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    if lang == 'en':
        buttons = [
            ["💬 Talk", "📅 Reminders"],
            ["👥 Events", "🆘 HELP"],
            ["👨‍👩‍👧 Family", "⚙️ Settings"],
            ["🎮 Games", "🌤️ Weather"],
            ["📸 Album", "🏥 Health"],
            ["💰 Budget", "📁 Export"],
            ["🌟 Premium", "❓ Help"]
        ]
    else:
        buttons = [
            ["💬 Поговорить", "📅 Напоминания"],
            ["👥 События", "🆘 ПОМОЩЬ"],
            ["👨‍👩‍👧 Семья", "⚙️ Настройки"],
            ["🎮 Игры", "🌤️ Погода"],
            ["📸 Альбом", "🏥 Здоровье"],
            ["💰 Бюджет", "📁 Экспорт"],
            ["🌟 Премиум", "❓ Помощь"]
        ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def get_games_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    if lang == 'en':
        buttons = [
            ["🔮 Riddle", "📖 Words"],
            ["✅ Truth or Lie", "❌ Exit game"]
        ]
    else:
        buttons = [
            ["🔮 Загадка", "📖 Слова"],
            ["✅ Правда или ложь", "❌ Выйти из игры"]
        ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


# ==================== КОНСТАНТЫ И СОСТОЯНИЯ ====================
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

class EventState(Enum):
    DATE = 1
    TIME = 2
    TITLE = 3
    DESCRIPTION = 4
    TYPE = 5
    TARGET_USER = 6
    REMIND_DAYS = 7

class HealthState(Enum):
    CHOOSE = 10
    DATE = 11
    TIME = 12
    SYSTOLIC = 13
    DIASTOLIC = 14
    PULSE = 15
    SUGAR = 16
    WEIGHT = 17
    NOTES = 18

class ExportState(Enum):
    CHOOSE = 20

class BudgetState(Enum):
    CHOOSE = 30
    TYPE = 31
    CATEGORY = 32
    AMOUNT = 33
    DATE = 34
    DESCRIPTION = 35


async def get_user_lang(update: Update) -> str:
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    if not lang:
        if update.effective_user and update.effective_user.language_code:
            if update.effective_user.language_code.startswith('ru'):
                lang = 'ru'
            else:
                lang = 'en'
        else:
            lang = 'ru'
        set_user_language(user_id, lang)
    return lang

# ---------------------- ОНБОРДИНГ ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    text = get_text(lang, 'start')
    keyboard = [["Я пользователь", "Я родственник"]] if lang == 'ru' else [["Elderly user", "Relative"]]
    await update.message.reply_text(
        text,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
    )
    return OnboardingState.CHOOSING_ROLE.value

async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    text = (update.message.text or "").strip().lower()
    if "родствен" in text or "relative" in text:
        context.user_data["role"] = Role.RELATIVE.value
        await update.message.reply_text(get_text(lang, 'choose_role'), reply_markup=ReplyKeyboardRemove())
        return OnboardingState.RELATIVE_CODE.value
    context.user_data["role"] = Role.SENIOR.value
    await update.message.reply_text(get_text(lang, 'senior_name'), reply_markup=ReplyKeyboardRemove())
    return OnboardingState.SENIOR_NAME.value

async def senior_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    context.user_data["name"] = (update.message.text or "").strip()
    await update.message.reply_text(get_text(lang, 'senior_age', name=context.user_data["name"]))
    return OnboardingState.SENIOR_AGE.value

async def senior_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text("Пожалуйста, введите число." if lang == 'ru' else "Please enter a number.")
        return OnboardingState.SENIOR_AGE.value
    context.user_data["age"] = int(text)
    await update.message.reply_text(get_text(lang, 'senior_city'))
    return OnboardingState.SENIOR_CITY.value

async def senior_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    context.user_data["city"] = (update.message.text or "").strip()
    await update.message.reply_text(get_text(lang, 'senior_interests'))
    return OnboardingState.SENIOR_INTERESTS.value

async def senior_interests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    context.user_data["interests"] = (update.message.text or "").strip()
    user = update.effective_user
    telegram_id = user.id if user else 0
    role = context.user_data.get("role", Role.SENIOR.value)
    name = context.user_data.get("name")
    age = context.user_data.get("age")
    city = context.user_data.get("city")
    interests = context.user_data.get("interests")
    upsert_user(telegram_id, role, name, age, city, interests)
    name_for_text = name or ("друг" if lang == 'ru' else "friend")
    await update.message.reply_text(
        get_text(lang, 'senior_complete', name=name_for_text),
        reply_markup=get_main_menu_keyboard(lang),
    )
    return ConversationHandler.END

async def relative_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    code = (update.message.text or "").strip()
    context.user_data["relative_code"] = code
    user = update.effective_user
    telegram_id = user.id if user else 0
    upsert_user(telegram_id, Role.RELATIVE.value, name=user.first_name if user else None)
    await update.message.reply_text(
        get_text(lang, 'relative_complete'),
        reply_markup=get_main_menu_keyboard(lang),
    )
    return ConversationHandler.END

# ---------------------- ОСНОВНЫЕ ОБРАБОТЧИКИ ----------------------
async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    text = update.message.text
    logger.info(f"🖲️ Button pressed: {text}")
    if text in ["💬 Поговорить", "💬 Talk"]:
        await handle_talk(update, context)
    elif text in ["📅 Напоминания", "📅 Reminders"]:
        await handle_reminders(update, context)
    elif text in ["👥 События", "👥 Events"]:
        await handle_events(update, context)
    elif text in ["🆘 ПОМОЩЬ", "🆘 HELP"]:
        await handle_sos(update, context)
    elif text in ["👨‍👩‍👧 Семья", "👨‍👩‍👧 Family"]:
        await handle_family(update, context)
    elif text in ["⚙️ Настройки", "⚙️ Settings"]:
        await handle_settings(update, context)
    elif text in ["🎮 Игры", "🎮 Games"]:
        await games_menu(update, context)
    elif text in ["🌤️ Погода", "🌤️ Weather"]:
        await weather_command(update, context)
    elif text in ["📸 Альбом", "📸 Album"]:
        await show_album(update, context)
    elif text in ["🏥 Здоровье", "🏥 Health"]:
        await health_menu(update, context)
    elif text in ["💰 Бюджет", "💰 Budget"]:
        await budget_menu(update, context)
    elif text in ["📁 Экспорт", "📁 Export"]:
        await export_menu(update, context)
    elif text in ["🌟 Премиум", "🌟 Premium"]:
        await premium_info(update, context)
    elif text in ["❓ Помощь", "❓ Help"]:
        await help_cmd(update, context)
    else:
        await handle_talk(update, context)

async def handle_talk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id if user else 0
    lang = await get_user_lang(update)
    name = context.user_data.get("name") or (user.first_name if user else ("друг" if lang == 'ru' else "friend"))
    last_text = (update.message.text or "").strip()
    if not last_text:
        return
    if user_id:
        save_message(user_id, "user", last_text)
    if user:
        log_activity(user.id, "talk")
    reply = await generate_companion_reply(last_text, name=name, user_id=user_id)
    if not reply:
        reply = "😊 Извините, я не смог придумать ответ. Попробуйте ещё раз."
    try:
        await update.message.reply_text(reply)
    except BadRequest as e:
        if "Message text is empty" in str(e):
            await update.message.reply_text("😊 Спасибо за сообщение!")
        else:
            raise
    if user_id and reply:
        save_message(user_id, "assistant", reply)

async def handle_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    telegram_id = user.id if user else 0
    lang = await get_user_lang(update)
    reminders = list_reminders(telegram_id)
    if not reminders:
        await update.message.reply_text(get_text(lang, 'no_reminders'))
        return
    lines = [get_text(lang, 'reminders_list')]
    for r in reminders:
        status = "✅" if r["enabled"] else "⏸"
        lines.append(f"{status} {r['time_local']} — {r['text']}")
    lines.append("\n/add_meds")
    await update.message.reply_text("\n".join(lines))

async def handle_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await get_user_lang(update)
    await update.message.reply_text(social_events_overview())
    await update.message.reply_text(
        "Дополнительно вы можете использовать команды:\n• /companions\n• /volunteers"
        if lang == 'ru' else
        "Additional commands:\n• /companions\n• /volunteers"
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
    lang = await get_user_lang(update)
    if user:
        log_activity(user.id, "sos")
    await update.message.reply_text(get_text(lang, 'sos_sent'))
    if user:
        user_name = context.user_data.get("name") or user.first_name or ("Родственник" if lang == 'ru' else "Relative")
        relatives = get_relatives_for_senior(user.id)
        for rel_id in relatives:
            try:
                await context.bot.send_message(
                    chat_id=rel_id,
                    text=get_text(lang, 'sos_notification', id=user.id),
                )
            except Exception as e:
                logger.warning("Failed to notify relative %s about SOS: %s", rel_id, e)
        family_id = get_family_id_for_user(user.id)
        if family_id:
            add_to_family_feed(family_id, user.id, user_name, get_text(lang, 'sos_feed'), "sos")
            notification = get_text(lang, 'sos_notify_family', name=user_name)
            await notify_family_members(family_id, user.id, context.bot, notification)

async def handle_family(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    telegram_id = user.id if user else 0
    lang = await get_user_lang(update)
    summary = get_activity_summary(telegram_id)
    talk = summary.get("talk", 0)
    meds_done = summary.get("reminder_done", 0)
    sos = summary.get("sos", 0)
    lines = ["Дневник активности за последние 24 часа:" if lang == 'ru' else "Activity log for last 24 hours:"]
    lines.append(f"💬 Разговоры: {talk}")
    lines.append(f"💊 Приёмы лекарств: {meds_done}")
    lines.append(f"🆘 SOS: {sos}")
    lines.append("\n" + ("Позже здесь появится общий семейный чат" if lang == 'ru' else "Family chat will appear here later"))
    await update.message.reply_text("\n".join(lines))

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await get_user_lang(update)
    await update.message.reply_text(get_text(lang, 'help_text'), parse_mode="Markdown")

async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_talk(update, context)

# ---------------------- НАПОМИНАНИЯ О ЛЕКАРСТВАХ ----------------------
async def add_meds_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    await update.message.reply_text(get_text(lang, 'add_reminder_prompt'), reply_markup=ReplyKeyboardRemove())
    return MedsState.ASK_TIME.value

async def add_meds_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    text = (update.message.text or "").strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await update.message.reply_text(get_text(lang, 'add_reminder_time_invalid'))
        return MedsState.ASK_TIME.value
    h, m = map(int, parts)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        await update.message.reply_text("Часы от 00 до 23, минуты от 00 до 59." if lang == 'ru' else "Hours 00-23, minutes 00-59.")
        return MedsState.ASK_TIME.value
    context.user_data["meds_time"] = f"{h:02d}:{m:02d}"
    await update.message.reply_text(get_text(lang, 'add_reminder_text_prompt'))
    return MedsState.ASK_TEXT.value

async def meds_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    text = job.data.get("text", "Пора принять лекарство.")
    try:
        await context.bot.send_message(chat_id=chat_id, text=f"💊 {text}")
        log_activity(chat_id, "reminder_done")
    except Exception as e:
        logger.warning("Failed to send meds reminder to %s: %s", chat_id, e)

async def add_meds_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    telegram_id = user.id if user else 0
    lang = await get_user_lang(update)
    meds_time = context.user_data.get("meds_time", "09:00")
    text = (update.message.text or "").strip() or ("Принять лекарство" if lang == 'ru' else "Take medication")
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
        get_text(lang, 'add_reminder_success', time=meds_time, text=text),
        reply_markup=get_main_menu_keyboard(lang),
    )
    return ConversationHandler.END

async def meds_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    await update.message.reply_text(get_text(lang, 'add_reminder_cancel'), reply_markup=get_main_menu_keyboard(lang))
    return ConversationHandler.END

# ---------------------- ЕЖЕДНЕВНАЯ ПРОВЕРКА ----------------------
async def daily_checkin(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    lang = get_user_language(chat_id)
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Как вы себя сегодня чувствуете? 🌷\nЕсли всё в порядке, можете просто написать мне пару слов." if lang == 'ru' else "How are you feeling today? 🌷\nIf everything is fine, just write me a few words.",
        )
    except Exception as e:
        logger.warning("Failed to send daily check-in to %s: %s", chat_id, e)

async def enable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    lang = await get_user_lang(update)
    job_queue: JobQueue = context.job_queue
    for job in job_queue.get_jobs_by_name(f"checkin-{chat_id}"):
        job.schedule_removal()
    job_queue.run_daily(daily_checkin, time=time(hour=10, minute=0), chat_id=chat_id, name=f"checkin-{chat_id}")
    await update.message.reply_text(
        "Хорошо, я буду каждый день в 10:00 спрашивать, как у вас дела. 🌞" if lang == 'ru' else "Okay, I'll ask you every day at 10:00 how you're doing. 🌞",
        reply_markup=get_main_menu_keyboard(lang),
    )

async def disable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    lang = await get_user_lang(update)
    job_queue: JobQueue = context.job_queue
    for job in job_queue.get_jobs_by_name(f"checkin-{chat_id}"):
        job.schedule_removal()
    await update.message.reply_text(
        "Ежедневный вопрос «Как дела?» отключен." if lang == 'ru' else "Daily 'How are you?' disabled.",
        reply_markup=get_main_menu_keyboard(lang),
    )

# ---------------------- ПРИВЯЗКА РОДСТВЕННИКА ----------------------
async def add_relative_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = await get_user_lang(update)
    if not context.args:
        await update.message.reply_text(
            "Использование: /add_relative <Telegram ID пожилого пользователя>.\nНапример: /add_relative 123456789" if lang == 'ru' else "Usage: /add_relative <Elderly user's Telegram ID>\nExample: /add_relative 123456789",
            reply_markup=get_main_menu_keyboard(lang),
        )
        return
    try:
        senior_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом." if lang == 'ru' else "ID must be a number.", reply_markup=get_main_menu_keyboard(lang))
        return
    if not user:
        await update.message.reply_text("Не удалось определить ваш Telegram ID." if lang == 'ru' else "Could not determine your Telegram ID.", reply_markup=get_main_menu_keyboard(lang))
        return
    add_relative_link(senior_id, user.id)
    await update.message.reply_text(
        f"Готово. Я связала вас с пользователем с Telegram ID {senior_id}.\nТеперь при нажатии SOS ему я постараюсь отправить вам уведомление." if lang == 'ru' else f"Done. I linked you with user Telegram ID {senior_id}.\nNow when they press SOS, I will try to notify you.",
        reply_markup=get_main_menu_keyboard(lang),
    )

# ---------------------- СЕМЕЙНАЯ ЛЕНТА ----------------------
async def family_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    user_name = context.user_data.get("name") or update.effective_user.first_name or ("Член семьи" if lang == 'ru' else "Family member")
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'), reply_markup=get_main_menu_keyboard(lang))
        return
    if not context.args:
        await update.message.reply_text(get_text(lang, 'family_send_usage'), reply_markup=get_main_menu_keyboard(lang))
        return
    message_text = " ".join(context.args)
    add_to_family_feed(family_id, user_id, user_name, message_text, "text")
    notification = get_text(lang, 'family_send_notify', name=user_name, message=message_text)
    await notify_family_members(family_id, user_id, context.bot, notification)
    await update.message.reply_text(get_text(lang, 'family_send_success'), reply_markup=get_main_menu_keyboard(lang))

async def family_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    try:
        family_id = get_family_id_for_user(user_id)
    except Exception as e:
        logger.error(f"Ошибка получения family_id: {e}")
        await update.message.reply_text(get_text(lang, 'db_error'), reply_markup=get_main_menu_keyboard(lang))
        return
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'), reply_markup=get_main_menu_keyboard(lang))
        return
    feed = get_family_feed(family_id, limit=15)
    if not feed:
        await update.message.reply_text(get_text(lang, 'family_feed_empty'), reply_markup=get_main_menu_keyboard(lang))
        return
    lines = [get_text(lang, 'family_feed_title')]
    for entry in feed:
        time_str = str(entry["created_at"])[:16].replace("-", ".").replace("T", " ")
        lines.append(f"👤 *{entry['author_name']}* ({time_str}):\n{entry['message']}\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=get_main_menu_keyboard(lang))

# ---------------------- КАЛЕНДАРЬ СОБЫТИЙ ----------------------
async def add_event_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    await update.message.reply_text(get_text(lang, 'event_add_date'), parse_mode="Markdown")
    return EventState.DATE.value

async def add_event_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    date_str = update.message.text.strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        await update.message.reply_text("❌ Неверный формат. Используйте ГГГГ-ММ-ДД, например 2025-12-31." if lang == 'ru' else "❌ Invalid format. Use YYYY-MM-DD, e.g., 2025-12-31.")
        return EventState.DATE.value
    context.user_data["event_date"] = date_str
    await update.message.reply_text(get_text(lang, 'event_add_time'))
    return EventState.TIME.value

async def add_event_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    time_str = update.message.text.strip()
    if time_str == "-":
        context.user_data["event_time"] = None
    elif not re.match(r'^\d{2}:\d{2}$', time_str):
        await update.message.reply_text("❌ Неверный формат времени. Используйте ЧЧ:ММ или '-' пропустить." if lang == 'ru' else "❌ Invalid time format. Use HH:MM or '-' to skip.")
        return EventState.TIME.value
    else:
        context.user_data["event_time"] = time_str
    await update.message.reply_text(get_text(lang, 'event_add_title'))
    return EventState.TITLE.value

async def add_event_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("Название не может быть пустым. Введите название:" if lang == 'ru' else "Title cannot be empty. Enter title:")
        return EventState.TITLE.value
    context.user_data["event_title"] = title
    await update.message.reply_text(get_text(lang, 'event_add_description'))
    return EventState.DESCRIPTION.value

async def add_event_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    desc = update.message.text.strip()
    context.user_data["event_description"] = desc if desc != "-" else None
    await update.message.reply_text(get_text(lang, 'event_add_type'))
    return EventState.TYPE.value

async def add_event_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    choice = update.message.text.strip()
    type_map = {"1": "birthday", "2": "holiday", "3": "meeting", "4": "other", "5": "birthday"}
    if choice not in type_map:
        await update.message.reply_text("Пожалуйста, выберите 1, 2, 3, 4 или 5." if lang == 'ru' else "Please select 1, 2, 3, 4 or 5.")
        return EventState.TYPE.value
    context.user_data["event_type"] = type_map[choice]
    if choice == "5":
        await update.message.reply_text(get_text(lang, 'event_add_target'))
        return EventState.TARGET_USER.value
    else:
        context.user_data["target_user_id"] = None
        await update.message.reply_text(get_text(lang, 'event_add_remind'))
        return EventState.REMIND_DAYS.value

async def add_event_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    text = update.message.text.strip()
    if text == "-":
        context.user_data["target_user_id"] = None
    else:
        try:
            context.user_data["target_user_id"] = int(text)
        except ValueError:
            await update.message.reply_text("❌ ID должен быть числом или '-'." if lang == 'ru' else "❌ ID must be a number or '-'.")
            return EventState.TARGET_USER.value
    await update.message.reply_text(get_text(lang, 'event_add_remind'))
    return EventState.REMIND_DAYS.value

async def add_event_remind_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    days_str = update.message.text.strip()
    days = int(days_str) if days_str.isdigit() else 1
    user_id = update.effective_user.id
    add_event(
        user_id=user_id,
        event_date=context.user_data["event_date"],
        title=context.user_data["event_title"],
        description=context.user_data.get("event_description"),
        event_time=context.user_data.get("event_time"),
        event_type=context.user_data.get("event_type", "other"),
        remind_before_days=days,
        target_user_id=context.user_data.get("target_user_id")
    )
    await update.message.reply_text(
        get_text(lang, 'event_add_success', date=context.user_data["event_date"], title=context.user_data["event_title"], days=days),
        reply_markup=get_main_menu_keyboard(lang),
    )
    context.user_data.clear()
    return -1

async def events_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    today = date.today().isoformat()
    events = get_events_for_user(user_id, from_date=today, limit=20)
    if not events:
        await update.message.reply_text(get_text(lang, 'events_list_empty'), reply_markup=get_main_menu_keyboard(lang))
        return
    lines = [get_text(lang, 'events_list_title')]
    for ev in events:
        time_str = f" {ev['time']}" if ev['time'] else ""
        title = ev['title']
        if ev['type'] == 'birthday' and ev.get('target_user_id'):
            user_info = get_user(ev['target_user_id'])
            if user_info:
                title = get_text(lang, 'event_birthday_title', name=user_info['name'])
        lines.append(f"• {ev['date']}{time_str} – *{title}*")
        if ev['description']:
            lines.append(f"  _{ev['description']}_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=get_main_menu_keyboard(lang))

async def delete_event_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    if not context.args:
        await update.message.reply_text(get_text(lang, 'event_delete_usage'), reply_markup=get_main_menu_keyboard(lang))
        return
    try:
        event_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом." if lang == 'ru' else "❌ ID must be a number.", reply_markup=get_main_menu_keyboard(lang))
        return
    user_id = update.effective_user.id
    success = delete_event(event_id, user_id)
    if success:
        await update.message.reply_text(get_text(lang, 'event_deleted', id=event_id), reply_markup=get_main_menu_keyboard(lang))
    else:
        await update.message.reply_text(get_text(lang, 'event_not_found'), reply_markup=get_main_menu_keyboard(lang))

# ---------------------- АНАЛИТИКА ----------------------
async def health_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
        if days > 30:
            days = 30
    stats = get_user_stats(user_id, days)
    reminder_stats = get_reminder_completion_rate(user_id, days)
    if reminder_stats['total_reminders'] > 0:
        report = get_text(lang, 'health_report',
            days=days, talks=stats['talks'], reminders=stats['reminders_done'],
            rate=reminder_stats['completion_rate'], sos=stats['sos'],
            voice=stats['voice'], total=stats['total'])
    else:
        report = get_text(lang, 'health_report_no_reminders',
            days=days, talks=stats['talks'], reminders=stats['reminders_done'],
            sos=stats['sos'], voice=stats['voice'], total=stats['total'])
    if reminder_stats['completion_rate'] < 50 and reminder_stats['total_reminders'] > 0:
        report += get_text(lang, 'health_recommendation_meds')
    if stats['talks'] == 0:
        report += get_text(lang, 'health_recommendation_talk')
    await update.message.reply_text(report, parse_mode="Markdown", reply_markup=get_main_menu_keyboard(lang))

async def family_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'), reply_markup=get_main_menu_keyboard(lang))
        return
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
        if days > 30:
            days = 30
    members_stats = get_family_stats(family_id, days)
    report = get_text(lang, 'family_report', days=days)
    total_talks, total_reminders, total_sos = 0,0,0
    for m in members_stats:
        report += get_text(lang, 'family_report_member', name=m['name'], talks=m['talks'], reminders=m['reminders_done'], sos=m['sos'])
        total_talks += m['talks']
        total_reminders += m['reminders_done']
        total_sos += m['sos']
    report += get_text(lang, 'family_report_total', talks=total_talks, reminders=total_reminders, sos=total_sos)
    await update.message.reply_text(report, parse_mode="Markdown", reply_markup=get_main_menu_keyboard(lang))

async def member_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'), reply_markup=get_main_menu_keyboard(lang))
        return
    if not context.args:
        await update.message.reply_text("📝 Использование: /member_stats <Telegram ID> [дни]" if lang == 'ru' else "📝 Usage: /member_stats <Telegram ID> [days]", reply_markup=get_main_menu_keyboard(lang))
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом." if lang == 'ru' else "❌ ID must be a number.", reply_markup=get_main_menu_keyboard(lang))
        return
    import sqlite3
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM relatives WHERE senior_id = ? AND relative_id = ?", (family_id, target_id))
    is_relative = cursor.fetchone() is not None
    conn.close()
    if target_id != family_id and not is_relative:
        await update.message.reply_text("❌ Этот пользователь не является членом вашей семьи." if lang == 'ru' else "❌ This user is not a member of your family.", reply_markup=get_main_menu_keyboard(lang))
        return
    days = 7
    if len(context.args) > 1 and context.args[1].isdigit():
        days = int(context.args[1])
        if days > 30:
            days = 30
    stats = get_user_stats(target_id, days)
    user_info = get_user(target_id)
    name = user_info["name"] if user_info else f"User_{target_id}"
    report = get_text(lang, 'member_stats', name=name, id=target_id, days=days,
                     talks=stats['talks'], reminders=stats['reminders_done'],
                     sos=stats['sos'], voice=stats['voice'], total=stats['total'])
    await update.message.reply_text(report, parse_mode="Markdown", reply_markup=get_main_menu_keyboard(lang))

# ---------------------- ИГРЫ И ВИКТОРИНЫ ----------------------
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
    lang = await get_user_lang(update)
    await update.message.reply_text(get_text(lang, 'games_menu'), reply_markup=get_games_menu_keyboard(lang), parse_mode="Markdown")

async def play_riddle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    riddle = random.choice(RIDDLES)
    save_game_state(user_id, "riddle", json.dumps({"question": riddle[0], "answer": riddle[1]}))
    await update.message.reply_text(get_text(lang, 'riddle_game', question=riddle[0]), parse_mode="Markdown")

async def play_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    save_game_state(user_id, "words", json.dumps({"last_letter": None, "used_words": []}))
    await update.message.reply_text(get_text(lang, 'words_game'), parse_mode="Markdown")

async def play_truth_or_lie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    question, answer = random.choice(TRUTH_OR_LIE)
    save_game_state(user_id, "truth_or_lie", json.dumps({"question": question, "answer": answer}))
    await update.message.reply_text(get_text(lang, 'truth_lie_game', question=question), parse_mode="Markdown")

async def exit_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    clear_game_state(user_id)
    await update.message.reply_text(get_text(lang, 'exit_game'), reply_markup=get_main_menu_keyboard(lang))

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
    lang = await get_user_lang(update)
    state = get_game_state(user_id)
    if not state:
        return
    game_name = state["game_name"]
    game_data = json.loads(state["game_data"])
    answer = update.message.text.strip().lower()
    if game_name == "riddle":
        correct = game_data["answer"]
        if answer == correct or answer in correct:
            await update.message.reply_text(get_text(lang, 'riddle_correct'), reply_markup=get_main_menu_keyboard(lang))
        else:
            await update.message.reply_text(get_text(lang, 'riddle_wrong', answer=correct), reply_markup=get_main_menu_keyboard(lang))
        clear_game_state(user_id)
    elif game_name == "words":
        last_letter = game_data.get("last_letter")
        used_words = set(game_data.get("used_words", []))
        if answer in used_words:
            await update.message.reply_text(get_text(lang, 'words_used', word=answer), reply_markup=get_main_menu_keyboard(lang))
            clear_game_state(user_id)
            return
        if last_letter and answer[0] != last_letter:
            await update.message.reply_text(get_text(lang, 'words_wrong_letter', letter=last_letter), reply_markup=get_main_menu_keyboard(lang))
            clear_game_state(user_id)
            return
        if len(answer) < 2:
            await update.message.reply_text(get_text(lang, 'words_too_short'), reply_markup=get_main_menu_keyboard(lang))
            clear_game_state(user_id)
            return
        used_words.add(answer)
        new_last = answer[-1]
        save_game_state(user_id, "words", json.dumps({"last_letter": new_last, "used_words": list(used_words)}))
        bot_word = find_word_on_letter(new_last, used_words)
        if bot_word:
            used_words.add(bot_word)
            next_letter = bot_word[-1]
            save_game_state(user_id, "words", json.dumps({"last_letter": next_letter, "used_words": list(used_words)}))
            await update.message.reply_text(get_text(lang, 'words_bot_turn', word=bot_word, letter=next_letter))
        else:
            await update.message.reply_text(get_text(lang, 'words_win', letter=new_last), reply_markup=get_main_menu_keyboard(lang))
            clear_game_state(user_id)
    elif game_name == "truth_or_lie":
        is_true = answer in ["правда","верно","да","true","truth"]
        is_false = answer in ["ложь","неправда","нет","false","lie"]
        if not (is_true or is_false):
            await update.message.reply_text(get_text(lang, 'truth_lie_prompt'))
            return
        correct = game_data["answer"]
        if (is_true and correct) or (is_false and not correct):
            await update.message.reply_text(get_text(lang, 'truth_lie_correct'), reply_markup=get_main_menu_keyboard(lang))
        else:
            await update.message.reply_text(get_text(lang, 'truth_lie_wrong', question=game_data["question"], answer='правда' if correct else 'ложь'), reply_markup=get_main_menu_keyboard(lang))
        clear_game_state(user_id)

# ---------------------- ГОЛОСОВЫЕ СООБЩЕНИЯ ----------------------
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user else 0
    lang = await get_user_lang(update)
    name = context.user_data.get("name") or (user.first_name if user else ("друг" if lang == 'ru' else "friend"))
    processing_msg = await update.message.reply_text(get_text(lang, 'voice_processing'))
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        audio_bytes = await file.download_as_bytearray()
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
            await processing_msg.edit_text(get_text(lang, 'voice_failed'), reply_markup=get_main_menu_keyboard(lang))
            return
        await processing_msg.edit_text(get_text(lang, 'voice_recognized', text=recognized_text), parse_mode="Markdown")
        reply = await generate_companion_reply(recognized_text, name=name, user_id=user_id)
        if not reply:
            reply = get_text(lang, 'talk_placeholder')
        await processing_msg.delete()
        await update.message.reply_text(reply, reply_markup=get_main_menu_keyboard(lang))
        if user:
            log_activity(user.id, "voice")
    except Exception as e:
        logger.error(f"Voice handling error: {e}")
        await processing_msg.edit_text(get_text(lang, 'voice_error'), reply_markup=get_main_menu_keyboard(lang))

# ---------------------- МЕДИАФАЙЛЫ ----------------------
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    lang = await get_user_lang(update)
    user_name = context.user_data.get("name") or user.first_name or ("Пользователь" if lang == 'ru' else "User")
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'), reply_markup=get_main_menu_keyboard(lang))
        return
    photo = update.message.photo[-1]
    caption = update.message.caption or ""
    save_media(family_id, user_id, user_name, "photo", photo.file_id, caption)
    await update.message.reply_text(get_text(lang, 'photo_saved'), reply_markup=get_main_menu_keyboard(lang))

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    lang = await get_user_lang(update)
    user_name = context.user_data.get("name") or user.first_name or ("Пользователь" if lang == 'ru' else "User")
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'), reply_markup=get_main_menu_keyboard(lang))
        return
    video = update.message.video
    caption = update.message.caption or ""
    save_media(family_id, user_id, user_name, "video", video.file_id, caption)
    await update.message.reply_text(get_text(lang, 'video_saved'), reply_markup=get_main_menu_keyboard(lang))

async def show_album(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'), reply_markup=get_main_menu_keyboard(lang))
        return
    media_list = get_family_media(family_id, limit=10)
    if not media_list:
        await update.message.reply_text(get_text(lang, 'album_empty'), reply_markup=get_main_menu_keyboard(lang))
        return
    for media in media_list:
        date_str = str(media['date'])[:16]
        if media['caption']:
            caption = get_text(lang, 'album_caption_with_text', date=date_str, author=media['author'], caption=media['caption'])
        else:
            caption = get_text(lang, 'album_caption', date=date_str, author=media['author'])
        if media['type'] == 'photo':
            await update.message.reply_photo(photo=media['file_id'], caption=caption)
        else:
            await update.message.reply_video(video=media['file_id'], caption=caption)

# ---------------------- ДНИ РОЖДЕНИЯ ----------------------
async def send_birthday_greetings(context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    birthdays = get_birthdays_for_date(today)
    for bday in birthdays:
        target_id = bday['target_user_id'] if bday['target_user_id'] else bday['user_id']
        user_info = get_user(target_id)
        name = user_info['name'] if user_info else f"User_{target_id}"
        lang = get_user_language(target_id)
        greeting = get_text(lang, 'birthday_greeting', name=name)
        try:
            await context.bot.send_message(chat_id=target_id, text=greeting, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Не удалось отправить поздравление {target_id}: {e}")
        family_id = get_family_id_for_user(target_id)
        if family_id:
            feed_lang = get_user_language(family_id) if get_user_language(family_id) else 'ru'
            add_to_family_feed(family_id, 0, "Бот", get_text(feed_lang, 'birthday_feed', name=name), "birthday")
            notification = get_text(feed_lang, 'birthday_notify', name=name)
            await notify_family_members(family_id, target_id, context.bot, notification)

# ---------------------- МЕДИЦИНСКИЙ ДНЕВНИК ----------------------
async def health_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    keyboard = [
        ["📝 Добавить запись", "📊 Статистика"],
        ["📋 Мои записи", "📈 Графики"],
        ["🔙 Назад"]
    ]
    if lang == 'en':
        keyboard = [
            ["📝 Add record", "📊 Statistics"],
            ["📋 My records", "📈 Charts"],
            ["🔙 Back"]
        ]
    await update.message.reply_text(
        "🏥 *Медицинский дневник*\n\nВыберите действие:" if lang == 'ru' else "🏥 *Health diary*\n\nChoose action:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return HealthState.CHOOSE.value

async def health_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    text = update.message.text
    if text in ["📝 Добавить запись", "📝 Add record"]:
        await update.message.reply_text("Введите дату в формате ГГГГ-ММ-ДД (например, 2025-12-31):" if lang == 'ru' else "Enter date in YYYY-MM-DD format (e.g., 2025-12-31):")
        return HealthState.DATE.value
    elif text in ["📊 Статистика", "📊 Statistics"]:
        await health_stats(update, context)
        return -1
    elif text in ["📋 Мои записи", "📋 My records"]:
        await health_list(update, context)
        return -1
    elif text in ["📈 Графики", "📈 Charts"]:
        await health_chart(update, context)
        return -1
    elif text in ["🔙 Назад", "🔙 Back"]:
        await update.message.reply_text("Возврат в главное меню." if lang == 'ru' else "Back to main menu.", reply_markup=get_main_menu_keyboard(lang))
        return -1
    return -1

async def health_add_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    date_str = update.message.text.strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        await update.message.reply_text("❌ Неверный формат. Используйте ГГГГ-ММ-ДД." if lang == 'ru' else "❌ Invalid format. Use YYYY-MM-DD.")
        return HealthState.DATE.value
    context.user_data["health_date"] = date_str
    await update.message.reply_text("Введите время (ЧЧ:ММ) или '-' пропустить:" if lang == 'ru' else "Enter time (HH:MM) or '-' skip:")
    return HealthState.TIME.value

async def health_add_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    time_str = update.message.text.strip()
    if time_str == "-":
        context.user_data["health_time"] = None
    elif re.match(r'^\d{2}:\d{2}$', time_str):
        context.user_data["health_time"] = time_str
    else:
        await update.message.reply_text("❌ Неверный формат. Введите ЧЧ:ММ или '-'." if lang == 'ru' else "❌ Invalid format. Enter HH:MM or '-'.")
        return HealthState.TIME.value
    await update.message.reply_text("Введите верхнее давление (систолическое) или '-' пропустить:" if lang == 'ru' else "Enter systolic pressure or '-' skip:")
    return HealthState.SYSTOLIC.value

async def health_add_systolic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    val = update.message.text.strip()
    if val == "-":
        context.user_data["health_systolic"] = None
    elif val.isdigit():
        context.user_data["health_systolic"] = int(val)
    else:
        await update.message.reply_text("Введите число или '-'." if lang == 'ru' else "Enter a number or '-'.")
        return HealthState.SYSTOLIC.value
    await update.message.reply_text("Введите нижнее давление (диастолическое) или '-' пропустить:" if lang == 'ru' else "Enter diastolic pressure or '-' skip:")
    return HealthState.DIASTOLIC.value

async def health_add_diastolic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    val = update.message.text.strip()
    if val == "-":
        context.user_data["health_diastolic"] = None
    elif val.isdigit():
        context.user_data["health_diastolic"] = int(val)
    else:
        await update.message.reply_text("Введите число или '-'." if lang == 'ru' else "Enter a number or '-'.")
        return HealthState.DIASTOLIC.value
    await update.message.reply_text("Введите пульс или '-' пропустить:" if lang == 'ru' else "Enter pulse or '-' skip:")
    return HealthState.PULSE.value

async def health_add_pulse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    val = update.message.text.strip()
    if val == "-":
        context.user_data["health_pulse"] = None
    elif val.isdigit():
        context.user_data["health_pulse"] = int(val)
    else:
        await update.message.reply_text("Введите число или '-'." if lang == 'ru' else "Enter a number or '-'.")
        return HealthState.PULSE.value
    await update.message.reply_text("Введите уровень сахара (ммоль/л) или '-' пропустить:" if lang == 'ru' else "Enter blood sugar (mmol/L) or '-' skip:")
    return HealthState.SUGAR.value

async def health_add_sugar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    val = update.message.text.strip()
    if val == "-":
        context.user_data["health_sugar"] = None
    else:
        try:
            context.user_data["health_sugar"] = float(val)
        except:
            await update.message.reply_text("Введите число (например, 5.6) или '-'." if lang == 'ru' else "Enter a number (e.g., 5.6) or '-'.")
            return HealthState.SUGAR.value
    await update.message.reply_text("Введите вес (кг) или '-' пропустить:" if lang == 'ru' else "Enter weight (kg) or '-' skip:")
    return HealthState.WEIGHT.value

async def health_add_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    val = update.message.text.strip()
    if val == "-":
        context.user_data["health_weight"] = None
    else:
        try:
            context.user_data["health_weight"] = float(val)
        except:
            await update.message.reply_text("Введите число (например, 70.5) или '-'." if lang == 'ru' else "Enter a number (e.g., 70.5) or '-'.")
            return HealthState.WEIGHT.value
    await update.message.reply_text("Введите заметки (или '-' пропустить):" if lang == 'ru' else "Enter notes (or '-' skip):")
    return HealthState.NOTES.value

async def health_add_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    notes = update.message.text.strip()
    if notes == "-":
        notes = None
    user_id = update.effective_user.id
    add_health_record(
        user_id=user_id,
        record_date=context.user_data["health_date"],
        record_time=context.user_data.get("health_time"),
        systolic=context.user_data.get("health_systolic"),
        diastolic=context.user_data.get("health_diastolic"),
        pulse=context.user_data.get("health_pulse"),
        blood_sugar=context.user_data.get("health_sugar"),
        weight=context.user_data.get("health_weight"),
        notes=notes
    )
    await update.message.reply_text("✅ Запись добавлена в медицинский дневник!" if lang == 'ru' else "✅ Record added to health diary!", reply_markup=get_main_menu_keyboard(lang))
    context.user_data.clear()
    return -1

async def health_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    stats = get_health_stats(user_id, days=30)
    if not stats or stats['records_count'] == 0:
        await update.message.reply_text("Нет медицинских записей за последние 30 дней." if lang == 'ru' else "No health records for the last 30 days.")
        return
    text = f"📊 *{'Статистика за последние 30 дней' if lang == 'ru' else 'Statistics for last 30 days'}*\n\n"
    if stats['systolic_avg']:
        text += f"💓 {'Давление' if lang == 'ru' else 'Pressure'}: {stats['systolic_avg']:.0f}/{stats['diastolic_avg']:.0f} ({'среднее' if lang == 'ru' else 'avg'})\n"
        text += f"   {'Последнее' if lang == 'ru' else 'Last'}: {stats['last_systolic']}/{stats['last_diastolic']}\n"
    if stats['pulse_avg']:
        text += f"💗 {'Пульс' if lang == 'ru' else 'Pulse'}: {stats['pulse_avg']:.0f} ({'среднее' if lang == 'ru' else 'avg'}), {'последний' if lang == 'ru' else 'last'}: {stats['last_pulse']}\n"
    if stats['sugar_avg']:
        text += f"🩸 {'Сахар' if lang == 'ru' else 'Sugar'}: {stats['sugar_avg']:.1f} ({'среднее' if lang == 'ru' else 'avg'}), {'последний' if lang == 'ru' else 'last'}: {stats['last_sugar']}\n"
    if stats['weight_avg']:
        text += f"⚖️ {'Вес' if lang == 'ru' else 'Weight'}: {stats['weight_avg']:.1f} кг ({'среднее' if lang == 'ru' else 'avg'}), {'последний' if lang == 'ru' else 'last'}: {stats['last_weight']}\n"
    text += f"\n📝 {'Всего записей' if lang == 'ru' else 'Total records'}: {stats['records_count']}"
    await update.message.reply_text(text, parse_mode="Markdown")

async def health_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    records = get_health_records(user_id, days=30)
    if not records:
        await update.message.reply_text("Нет записей." if lang == 'ru' else "No records.")
        return
    lines = ["📋 *Ваши медицинские записи (последние 10)*\n" if lang == 'ru' else "📋 *Your health records (last 10)*\n"]
    for r in records[:10]:
        time_str = f" {r['time']}" if r['time'] else ""
        lines.append(f"📅 {r['date']}{time_str}")
        if r['systolic'] and r['diastolic']:
            lines.append(f"   {'Давление' if lang == 'ru' else 'Pressure'}: {r['systolic']}/{r['diastolic']}")
        if r['pulse']:
            lines.append(f"   {'Пульс' if lang == 'ru' else 'Pulse'}: {r['pulse']}")
        if r['blood_sugar']:
            lines.append(f"   {'Сахар' if lang == 'ru' else 'Sugar'}: {r['blood_sugar']}")
        if r['weight']:
            lines.append(f"   {'Вес' if lang == 'ru' else 'Weight'}: {r['weight']} кг")
        if r['notes']:
            lines.append(f"   📝 {r['notes']}")
        lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def health_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    if not is_premium(user_id):
        await update.message.reply_text(get_text(lang, 'premium_only'), reply_markup=get_main_menu_keyboard(lang))
        return
    records = get_health_records(user_id, days=30)
    if not records:
        await update.message.reply_text("Нет данных для графика." if lang == 'ru' else "No data for chart.")
        return
    records_sorted = sorted(records, key=lambda x: x['date'])
    dates = [r['date'] for r in records_sorted]
    systolic = [r['systolic'] for r in records_sorted if r['systolic']]
    diastolic = [r['diastolic'] for r in records_sorted if r['diastolic']]
    if not systolic and not diastolic:
        await update.message.reply_text("Нет данных о давлении." if lang == 'ru' else "No blood pressure data.")
        return
    try:
        import matplotlib.pyplot as plt
        import io
        plt.figure(figsize=(10,5))
        if systolic:
            plt.plot(dates, systolic, marker='o', label='Systolic' if lang == 'en' else 'Верхнее')
        if diastolic:
            plt.plot(dates, diastolic, marker='s', label='Diastolic' if lang == 'en' else 'Нижнее')
        plt.xticks(rotation=45)
        plt.legend()
        plt.title('Blood pressure dynamics' if lang == 'en' else 'Динамика давления')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        await update.message.reply_photo(photo=buf, caption="📈 Blood pressure chart" if lang == 'en' else "📈 График давления")
        plt.close()
    except ImportError:
        await update.message.reply_text("⚠️ Для графиков требуется библиотека matplotlib. Установите её." if lang == 'ru' else "⚠️ Matplotlib is required for charts. Please install it.")

# ---------------------- ЭКСПОРТ ДАННЫХ ----------------------
async def export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    if not is_premium(update.effective_user.id):
        await update.message.reply_text(get_text(lang, 'premium_only'), reply_markup=get_main_menu_keyboard(lang))
        return
    keyboard = [
        ["📋 История диалогов", "🏥 Медицинские записи"],
        ["👨‍👩‍👧 Семейная лента", "🔙 Назад"]
    ]
    if lang == 'en':
        keyboard = [
            ["📋 Chat history", "🏥 Health records"],
            ["👨‍👩‍👧 Family feed", "🔙 Back"]
        ]
    await update.message.reply_text(
        "📁 *Экспорт данных*\n\nВыберите, что экспортировать:" if lang == 'ru' else "📁 *Data export*\n\nChoose what to export:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return ExportState.CHOOSE.value

async def export_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    if choice in ["📋 История диалогов", "📋 Chat history"]:
        csv_data = export_chat_history(user_id)
        await update.message.reply_document(document=io.BytesIO(csv_data.encode('utf-8')), filename="chat_history.csv")
    elif choice in ["🏥 Медицинские записи", "🏥 Health records"]:
        csv_data = export_health_records(user_id)
        await update.message.reply_document(document=io.BytesIO(csv_data.encode('utf-8')), filename="health_records.csv")
    elif choice in ["👨‍👩‍👧 Семейная лента", "👨‍👩‍👧 Family feed"]:
        family_id = get_family_id_for_user(user_id)
        if family_id:
            csv_data = export_family_feed(family_id)
            await update.message.reply_document(document=io.BytesIO(csv_data.encode('utf-8')), filename="family_feed.csv")
        else:
            await update.message.reply_text(get_text(lang, 'not_relative'), reply_markup=get_main_menu_keyboard(lang))
    elif choice in ["🔙 Назад", "🔙 Back"]:
        await update.message.reply_text("Возврат в главное меню." if lang == 'ru' else "Back to main menu.", reply_markup=get_main_menu_keyboard(lang))
        return -1
    return -1

# ---------------------- СЕМЕЙНЫЙ БЮДЖЕТ ----------------------
async def budget_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    if not is_premium(update.effective_user.id):
        await update.message.reply_text(get_text(lang, 'premium_only'), reply_markup=get_main_menu_keyboard(lang))
        return -1
    keyboard = [
        ["➕ Добавить транзакцию", "📊 Статистика"],
        ["📋 Список операций", "🏷️ Категории"],
        ["🔙 Назад"]
    ]
    if lang == 'en':
        keyboard = [
            ["➕ Add transaction", "📊 Statistics"],
            ["📋 Transaction list", "🏷️ Categories"],
            ["🔙 Back"]
        ]
    await update.message.reply_text(
        get_text(lang, 'budget_menu'),
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BudgetState.CHOOSE.value

async def budget_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    text = update.message.text
    if text in ["➕ Добавить транзакцию", "➕ Add transaction"]:
        await update.message.reply_text(get_text(lang, 'budget_add_type'))
        return BudgetState.TYPE.value
    elif text in ["📊 Статистика", "📊 Statistics"]:
        await budget_stats(update, context)
        return -1
    elif text in ["📋 Список операций", "📋 Transaction list"]:
        await budget_list(update, context)
        return -1
    elif text in ["🏷️ Категории", "🏷️ Categories"]:
        await budget_categories(update, context)
        return -1
    elif text in ["🔙 Назад", "🔙 Back"]:
        await update.message.reply_text("Возврат в главное меню." if lang == 'ru' else "Back to main menu.", reply_markup=get_main_menu_keyboard(lang))
        return -1
    return -1

async def budget_add_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    choice = update.message.text.strip()
    if choice == "1":
        context.user_data["budget_type"] = "income"
    elif choice == "2":
        context.user_data["budget_type"] = "expense"
    else:
        await update.message.reply_text("Пожалуйста, введите 1 или 2." if lang == 'ru' else "Please enter 1 or 2.")
        return BudgetState.TYPE.value
    categories = get_categories()
    cat_list = "\n".join([f"{c['name']} ({c['icon']})" for c in categories if c['type'] == context.user_data["budget_type"]])
    await update.message.reply_text(get_text(lang, 'budget_add_category') + "\n" + cat_list)
    return BudgetState.CATEGORY.value

async def budget_add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    category_name = update.message.text.strip()
    categories = get_categories()
    valid = any(c['name'] == category_name for c in categories if c['type'] == context.user_data["budget_type"])
    if not valid:
        await update.message.reply_text("❌ Неверная категория. Попробуйте ещё раз." if lang == 'ru' else "❌ Invalid category. Try again.")
        return BudgetState.CATEGORY.value
    context.user_data["budget_category"] = category_name
    await update.message.reply_text(get_text(lang, 'budget_add_amount'))
    return BudgetState.AMOUNT.value

async def budget_add_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    try:
        amount = float(update.message.text.strip())
        if amount <= 0:
            raise ValueError
        context.user_data["budget_amount"] = amount
    except:
        await update.message.reply_text("❌ Введите положительное число." if lang == 'ru' else "❌ Enter a positive number.")
        return BudgetState.AMOUNT.value
    await update.message.reply_text(get_text(lang, 'budget_add_date'))
    return BudgetState.DATE.value

async def budget_add_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    date_str = update.message.text.strip()
    if date_str == "-":
        date_str = date.today().isoformat()
    elif not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        await update.message.reply_text("❌ Неверный формат. Используйте ГГГГ-ММ-ДД или '-'." if lang == 'ru' else "❌ Invalid format. Use YYYY-MM-DD or '-'.")
        return BudgetState.DATE.value
    context.user_data["budget_date"] = date_str
    await update.message.reply_text(get_text(lang, 'budget_add_desc'))
    return BudgetState.DESCRIPTION.value

async def budget_add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    desc = update.message.text.strip()
    if desc == "-":
        desc = None
    user_id = update.effective_user.id
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'))
        return -1
    add_transaction(
        user_id=user_id,
        family_id=family_id,
        amount=context.user_data["budget_amount"],
        category=context.user_data["budget_category"],
        transaction_type=context.user_data["budget_type"],
        transaction_date=context.user_data["budget_date"],
        description=desc
    )
    await update.message.reply_text(get_text(lang, 'budget_add_success'), reply_markup=get_main_menu_keyboard(lang))
    context.user_data.clear()
    return -1

async def budget_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'))
        return
    summary = get_budget_summary(family_id)
    breakdown = get_category_breakdown(family_id)
    text = get_text(lang, 'budget_stats_text', income=summary['income'], expense=summary['expense'], balance=summary['balance'])
    text += "\n" + get_text(lang, 'budget_breakdown')
    for cat, data in breakdown.items():
        if data['type'] == 'expense':
            text += f"\n• {cat}: {data['total']:.2f} ₽"
    await update.message.reply_text(text, parse_mode="Markdown")

async def budget_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'))
        return
    transactions = get_transactions(family_id, limit=20)
    if not transactions:
        await update.message.reply_text(get_text(lang, 'budget_list_empty'))
        return
    lines = [get_text(lang, 'budget_list_header')]
    for t in transactions[:20]:
        sign = "+" if t['type'] == 'income' else "-"
        lines.append(f"{t['date']} {t['category']}: {sign}{t['amount']:.2f} ₽")
        if t['description']:
            lines.append(f"   📝 {t['description']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def budget_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await get_user_lang(update)
    categories = get_categories()
    text = "🏷️ *Категории бюджета:*\n\n"
    for cat in categories:
        text += f"{cat['icon']} {cat['name']} ({'доход' if cat['type']=='income' else 'расход'})\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------------------- ПРЕМИУМ ----------------------
async def premium_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    premium = is_premium(user_id)
    if premium:
        expiry = get_premium_expiry(user_id)
        date_str = expiry.strftime('%d.%m.%Y') if expiry else "???"
        text = get_text(lang, 'premium_active', date=date_str)
    else:
        text = get_text(lang, 'premium_inactive')
    await update.message.reply_text(get_text(lang, 'premium_info', status=text), parse_mode="Markdown", reply_markup=get_main_menu_keyboard(lang))

async def activate_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    if not context.args:
        await update.message.reply_text(get_text(lang, 'activate_usage'))
        return
    code = context.args[0].upper()
    if activate_code(code, user_id):
        await update.message.reply_text(get_text(lang, 'activate_success'), reply_markup=get_main_menu_keyboard(lang))
    else:
        await update.message.reply_text(get_text(lang, 'activate_fail'))

async def gen_premium_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ADMIN_ID = 8091619207  # ЗАМЕНИТЕ НА СВОЙ TELEGRAM ID
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Недостаточно прав.")
        return
    lang = await get_user_lang(update)
    if not context.args:
        await update.message.reply_text(get_text(lang, 'gen_code_usage'))
        return
    try:
        days = int(context.args[0])
        code = generate_code(days)
        await update.message.reply_text(get_text(lang, 'gen_code_success', code=code, days=days), parse_mode="Markdown")
    except:
        await update.message.reply_text(get_text(lang, 'gen_code_error'))

# ---------------------- ОСТАЛЬНЫЕ КОМАНДЫ ----------------------
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
    lang = await get_user_lang(update)
    clear_chat_history(user_id)
    await update.message.reply_text("🧹 История диалогов очищена!" if lang == 'ru' else "🧹 Chat history cleared!", reply_markup=get_main_menu_keyboard(lang))

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await get_user_lang(update)
    await update.message.reply_text(get_text(lang, 'help_text'), parse_mode="Markdown", reply_markup=get_main_menu_keyboard(lang))

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await get_user_lang(update)
    await update.message.reply_text(get_text(lang, 'menu'), reply_markup=get_main_menu_keyboard(lang))

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = await get_user_lang(update)
    name = context.user_data.get("name") or (user.first_name if user else ("друг" if lang == 'ru' else "friend"))
    city = context.user_data.get("city")
    if not city:
        await update.message.reply_text(get_text(lang, 'weather_unknown_city', name=name), reply_markup=get_main_menu_keyboard(lang))
        return
    summary = await get_weather_summary(city)
    if not summary:
        await update.message.reply_text(get_text(lang, 'weather_error'), reply_markup=get_main_menu_keyboard(lang))
        return
    await update.message.reply_text(get_text(lang, 'weather_forecast', name=name, summary=summary), reply_markup=get_main_menu_keyboard(lang))

async def set_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    text = update.message.text.lower()
    match = re.search(r'(мой город|живу в|город|my city|i live in)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', text)
    if match:
        city = match.group(2).strip().capitalize()
        if len(city) > 1:
            user = get_user(user_id) or {}
            upsert_user(user_id, role=user.get("role", "senior"), name=user.get("name"), city=city)
            await update.message.reply_text(get_text(lang, 'city_remembered', city=city), parse_mode="Markdown", reply_markup=get_main_menu_keyboard(lang))

async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    if not context.args:
        await update.message.reply_text(get_text(lang, 'lang_usage'))
        return
    new_lang = context.args[0].lower()
    if new_lang not in ['ru', 'en']:
        await update.message.reply_text(get_text(lang, 'lang_invalid'))
        return
    set_user_language(user_id, new_lang)
    await update.message.reply_text(get_text(new_lang, 'lang_changed'), reply_markup=get_main_menu_keyboard(new_lang))

# ---------------------- ПОСТРОЕНИЕ ПРИЛОЖЕНИЯ ----------------------
def build_application():
    settings = get_settings()
    init_db()
    init_chat_history_table()
    init_family_feed_table()
    init_calendar_table()
    init_games_table()
    init_media_table()
    init_health_table()
    init_budget_table()
    init_premium_tables()

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
            EventState.DATE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_date)],
            EventState.TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_time)],
            EventState.TITLE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_title)],
            EventState.DESCRIPTION.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_description)],
            EventState.TYPE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_type)],
            EventState.TARGET_USER.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_target_user)],
            EventState.REMIND_DAYS.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_event_remind_days)],
        },
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(event_conv)

    health_conv = ConversationHandler(
        entry_points=[CommandHandler("health", health_menu)],
        states={
            HealthState.CHOOSE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, health_menu_router)],
            HealthState.DATE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, health_add_date)],
            HealthState.TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, health_add_time)],
            HealthState.SYSTOLIC.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, health_add_systolic)],
            HealthState.DIASTOLIC.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, health_add_diastolic)],
            HealthState.PULSE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, health_add_pulse)],
            HealthState.SUGAR.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, health_add_sugar)],
            HealthState.WEIGHT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, health_add_weight)],
            HealthState.NOTES.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, health_add_notes)],
        },
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(health_conv)
    application.add_handler(CommandHandler("health_stats", health_stats))
    application.add_handler(CommandHandler("health_list", health_list))
    application.add_handler(CommandHandler("health_chart", health_chart))

    export_conv = ConversationHandler(
        entry_points=[CommandHandler("export", export_menu)],
        states={ExportState.CHOOSE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, export_choice)]},
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(export_conv)

    budget_conv = ConversationHandler(
        entry_points=[CommandHandler("budget", budget_menu)],
        states={
            BudgetState.CHOOSE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_menu_router)],
            BudgetState.TYPE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_add_type)],
            BudgetState.CATEGORY.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_add_category)],
            BudgetState.AMOUNT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_add_amount)],
            BudgetState.DATE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_add_date)],
            BudgetState.DESCRIPTION.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, budget_add_description)],
        },
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(budget_conv)
    application.add_handler(CommandHandler("budget_stats", budget_stats))
    application.add_handler(CommandHandler("budget_list", budget_list))
    application.add_handler(CommandHandler("budget_categories", budget_categories))

    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("enable_checkin", enable_checkin))
    application.add_handler(CommandHandler("disable_checkin", disable_checkin))
    application.add_handler(CommandHandler("voice_help", voice_help))
    application.add_handler(CommandHandler("add_relative", add_relative_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("menu", menu_cmd))
    application.add_handler(CommandHandler("clear_history", clear_history_cmd))
    application.add_handler(CommandHandler("lang", lang_command))

    application.add_handler(CommandHandler("family_send", family_send))
    application.add_handler(CommandHandler("family_feed", family_feed))

    application.add_handler(CommandHandler("events_list", events_list))
    application.add_handler(CommandHandler("delete_event", delete_event_cmd))

    application.add_handler(CommandHandler("health_report", health_report))
    application.add_handler(CommandHandler("family_report", family_report))
    application.add_handler(CommandHandler("member_stats", member_stats))

    application.add_handler(CommandHandler("games", games_menu))
    application.add_handler(MessageHandler(filters.Regex("^🔮 Загадка$|^🔮 Riddle$"), play_riddle))
    application.add_handler(MessageHandler(filters.Regex("^📖 Слова$|^📖 Words$"), play_words))
    application.add_handler(MessageHandler(filters.Regex("^✅ Правда или ложь$|^✅ Truth or Lie$"), play_truth_or_lie))
    application.add_handler(MessageHandler(filters.Regex("^❌ Выйти из игры$|^❌ Exit game$"), exit_game))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_game_answer), group=1)

    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(CommandHandler("album", show_album))

    application.add_handler(CommandHandler("premium", premium_info))
    application.add_handler(CommandHandler("activate", activate_premium))
    application.add_handler(CommandHandler("gen_code", gen_premium_code))

    for cmd in [
        companions_cmd, volunteers_cmd, health_extra_cmd, helper_cmd,
        nostalgia_cmd, courses_cmd, achievements_cmd, admin_analytics_cmd
    ]:
        application.add_handler(CommandHandler(cmd.__name__.replace("_cmd", ""), cmd))

    application.add_handler(MessageHandler(filters.Regex(r'(мой город|живу в|город|my city|i live in)'), set_city))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_router), group=2)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text), group=3)

    job_queue = application.job_queue
    if job_queue:
        async def daily_event_reminder(context: ContextTypes.DEFAULT_TYPE):
            today = date.today()
            today_events = get_events_by_date(today.isoformat())
            for ev in today_events:
                time_msg = f" в {ev['time']}" if ev['time'] else ""
                lang = get_user_language(ev['user_id'])
                text = f"🔔 *{'Напоминание о событии сегодня' if lang == 'ru' else 'Reminder of event today'}{time_msg}:*\n{ev['title']}\n{ev['description'] or ''}"
                await context.bot.send_message(chat_id=ev['user_id'], text=text, parse_mode="Markdown")
            tomorrow = today + timedelta(days=1)
            tomorrow_events = get_events_by_date(tomorrow.isoformat())
            for ev in tomorrow_events:
                if ev['remind_before_days'] >= 1:
                    lang = get_user_language(ev['user_id'])
                    text = f"📅 *{'Напоминание:' if lang == 'ru' else 'Reminder:'}* {'завтра событие' if lang == 'ru' else 'tomorrow event'} «{ev['title']}»."
                    await context.bot.send_message(chat_id=ev['user_id'], text=text, parse_mode="Markdown")
        job_queue.run_daily(daily_event_reminder, time=time(hour=9, minute=0))
        job_queue.run_daily(send_birthday_greetings, time=time(hour=9, minute=5))

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
