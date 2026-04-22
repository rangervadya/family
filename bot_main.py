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
from typing import Final, Dict
from datetime import time, date, timedelta
from flask import Flask

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ConversationHandler,
    ContextTypes, JobQueue, filters
)
from telegram.request import HTTPXRequest
from telegram.error import NetworkError, TimedOut, BadRequest

from bot_config import get_settings
from ai_stubs import generate_companion_reply
from storage import (
    init_db, upsert_user, list_reminders, add_reminder, log_activity,
    get_activity_summary, add_relative_link, get_relatives_for_senior,
    init_chat_history_table, save_message, clear_chat_history,
    init_family_feed_table, get_family_id_for_user, add_to_family_feed, get_family_feed,
    init_calendar_table, add_event, get_events_for_user, delete_event, get_events_by_date,
    init_games_table, save_game_state, get_game_state, clear_game_state,
    init_media_table, save_media, get_family_media,
    get_birthdays_for_date,
    get_user_language, set_user_language,
    init_health_table, add_health_record, get_health_records, get_health_stats,
    export_chat_history, export_health_records, export_family_feed,
    init_budget_table, add_transaction, get_transactions, get_budget_summary, get_categories, get_category_breakdown,
    init_premium_tables, is_premium, add_premium_user, generate_code, activate_code, get_premium_expiry,
    get_user
)
from weather import get_weather_summary
from features_stub import (
    social_events_overview, social_companions_info, social_volunteers_info,
    health_extra_info, home_helper_info, games_menu_text, nostalgia_menu_text,
    courses_menu_text, achievements_text, voice_interface_info, analytics_info_text
)

import speech_recognition as sr
from pydub import AudioSegment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)

@flask_app.route('/')
@flask_app.route('/health')
def health_check():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False)

# ---------- Многоязычность ----------
TEXTS = {
    'ru': {
        'start': "Здравствуйте! Я бот-компаньон «Семья». Давайте познакомимся.\nКто вы?\n➤ Я пожилой пользователь\n➤ Я родственник/опекун",
        'choose_role': "Хорошо! Вы родственник.\nВведите код привязки.",
        'senior_name': "Как вас зовут?",
        'senior_age': "Сколько вам лет?",
        'senior_city': "В каком городе вы живёте?",
        'senior_interests': "Расскажите о ваших увлечениях.",
        'senior_complete': "Спасибо, {name}! Вот главное меню.",
        'relative_complete': "Спасибо! Вот главное меню.",
        'menu': "Главное меню:",
        'no_reminders': "Нет напоминаний. /add_meds",
        'sos_sent': "SOS отправлен.",
        'family_feed_empty': "Лента пуста.",
        'not_relative': "Вы не привязаны к семье.",
        'premium_only': "⭐ Только для премиум. /premium",
        'budget_menu': "💰 Семейный бюджет",
        'budget_add_success': "✅ Транзакция добавлена!",
        'activate_usage': "Введите код: /activate <код>",
        'activate_success': "✅ Премиум активирован!",
        'activate_fail': "❌ Неверный код.",
        'premium_info': "🌟 Премиум-доступ\n\n{status}",
        'premium_active': "Активен до {date}",
        'premium_inactive': "Платные функции: графики, бюджет, экспорт. 300₽/мес. Обратитесь к @admin",
    },
    'en': {}
}

def get_text(lang, key, **kwargs):
    text = TEXTS.get(lang, TEXTS['ru']).get(key, key)
    return text.format(**kwargs) if kwargs else text

def get_main_menu_keyboard(lang: str, premium: bool) -> ReplyKeyboardMarkup:
    if premium:
        buttons = [
            ["💬 Поговорить", "📅 Напоминания"],
            ["👥 События", "🆘 ПОМОЩЬ"],
            ["👨‍👩‍👧 Семья", "⚙️ Настройки"],
            ["🎮 Игры", "🌤️ Погода"],
            ["📸 Альбом", "🏥 Здоровье"],
            ["💰 Бюджет", "📁 Экспорт"],
            ["🌟 Премиум", "❓ Помощь"]
        ]
    else:
        buttons = [
            ["💬 Поговорить", "📅 Напоминания"],
            ["👥 События", "🆘 ПОМОЩЬ"],
            ["👨‍👩‍👧 Семья", "⚙️ Настройки"],
            ["🎮 Игры", "🌤️ Погода"],
            ["📸 Альбом", "🏥 Здоровье"],
            ["🌟 Премиум", "❓ Помощь"]
        ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def get_games_menu_keyboard(lang):
    return ReplyKeyboardMarkup([["🔮 Загадка", "📖 Слова"], ["✅ Правда или ложь", "❌ Выйти из игры"]], resize_keyboard=True)

# ---------- Состояния ----------
class Role(Enum): SENIOR = "senior"; RELATIVE = "relative"
class OnboardingState(Enum): CHOOSING_ROLE = auto(); SENIOR_NAME = auto(); SENIOR_AGE = auto(); SENIOR_CITY = auto(); SENIOR_INTERESTS = auto(); RELATIVE_CODE = auto()
class MedsState(Enum): ASK_TIME = auto(); ASK_TEXT = auto()
class EventState(Enum): DATE = 1; TIME = 2; TITLE = 3; DESCRIPTION = 4; TYPE = 5; TARGET_USER = 6; REMIND_DAYS = 7
class HealthState(Enum): CHOOSE = 10; DATE = 11; TIME = 12; SYSTOLIC = 13; DIASTOLIC = 14; PULSE = 15; SUGAR = 16; WEIGHT = 17; NOTES = 18
class ExportState(Enum): CHOOSE = 20
class BudgetState(Enum): CHOOSE = 30; TYPE = 31; CATEGORY = 32; AMOUNT = 33; DATE = 34; DESCRIPTION = 35

async def get_user_lang(update):
    uid = update.effective_user.id
    lang = get_user_language(uid)
    if not lang:
        lang = 'ru'
        set_user_language(uid, lang)
    return lang

# ---------- ОНБОРДИНГ (исправлен) ----------
async def start(update, context):
    lang = await get_user_lang(update)
    keyboard = [["Я пользователь", "Я родственник"]]
    await update.message.reply_text(get_text(lang, 'start'), reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True))
    return OnboardingState.CHOOSING_ROLE.value

async def choose_role(update, context):
    lang = await get_user_lang(update)
    text = update.message.text.lower()
    if "родствен" in text:
        context.user_data["role"] = Role.RELATIVE.value
        await update.message.reply_text(get_text(lang, 'choose_role'), reply_markup=ReplyKeyboardRemove())
        return OnboardingState.RELATIVE_CODE.value
    context.user_data["role"] = Role.SENIOR.value
    await update.message.reply_text(get_text(lang, 'senior_name'), reply_markup=ReplyKeyboardRemove())
    return OnboardingState.SENIOR_NAME.value

async def senior_name(update, context):
    lang = await get_user_lang(update)
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(get_text(lang, 'senior_age'))
    return OnboardingState.SENIOR_AGE.value

async def senior_age(update, context):
    lang = await get_user_lang(update)
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Введите число.")
        return OnboardingState.SENIOR_AGE.value
    context.user_data["age"] = int(text)
    await update.message.reply_text(get_text(lang, 'senior_city'))
    return OnboardingState.SENIOR_CITY.value

async def senior_city(update, context):
    lang = await get_user_lang(update)
    context.user_data["city"] = update.message.text.strip()
    await update.message.reply_text(get_text(lang, 'senior_interests'))
    return OnboardingState.SENIOR_INTERESTS.value

async def senior_interests(update, context):
    lang = await get_user_lang(update)
    context.user_data["interests"] = update.message.text.strip()
    user = update.effective_user
    upsert_user(user.id, context.user_data["role"], name=context.user_data.get("name"), age=context.user_data.get("age"), city=context.user_data.get("city"), interests=context.user_data.get("interests"))
    premium = is_premium(user.id)
    await update.message.reply_text(get_text(lang, 'senior_complete', name=context.user_data.get("name", "друг")), reply_markup=get_main_menu_keyboard(lang, premium))
    return ConversationHandler.END

async def relative_code(update, context):
    lang = await get_user_lang(update)
    code = update.message.text.strip()
    user = update.effective_user
    upsert_user(user.id, Role.RELATIVE.value, name=user.first_name)
    premium = is_premium(user.id)
    await update.message.reply_text(get_text(lang, 'relative_complete'), reply_markup=get_main_menu_keyboard(lang, premium))
    return ConversationHandler.END

# ---------- ОСНОВНОЙ РОУТЕР ----------
async def main_menu_router(update, context):
    lang = await get_user_lang(update)
    premium = is_premium(update.effective_user.id)
    text = update.message.text
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
        if not premium:
            await update.message.reply_text(get_text(lang, 'premium_only'), reply_markup=get_main_menu_keyboard(lang, premium))
        else:
            await budget_menu(update, context)
    elif text in ["📁 Экспорт", "📁 Export"]:
        if not premium:
            await update.message.reply_text(get_text(lang, 'premium_only'), reply_markup=get_main_menu_keyboard(lang, premium))
        else:
            await export_menu(update, context)
    elif text in ["🌟 Премиум", "🌟 Premium"]:
        await premium_info(update, context)
    elif text in ["❓ Помощь", "❓ Help"]:
        await help_cmd(update, context)
    else:
        await handle_talk(update, context)

async def handle_talk(update, context):
    user = update.effective_user
    user_id = user.id
    lang = await get_user_lang(update)
    name = context.user_data.get("name") or user.first_name
    last_text = update.message.text.strip()
    if not last_text:
        return
    save_message(user_id, "user", last_text)
    log_activity(user_id, "talk")
    reply = await generate_companion_reply(last_text, name=name, user_id=user_id)
    await update.message.reply_text(reply)
    if reply:
        save_message(user_id, "assistant", reply)

async def handle_reminders(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    reminders = list_reminders(user_id)
    if not reminders:
        await update.message.reply_text(get_text(lang, 'no_reminders'))
        return
    lines = ["📋 Ваши напоминания:"]
    for r in reminders:
        lines.append(f"{'✅' if r['enabled'] else '⏸'} {r['time_local']} — {r['text']}")
    await update.message.reply_text("\n".join(lines))

async def handle_events(update, context):
    await update.message.reply_text(social_events_overview())

async def notify_family_members(family_id, exclude_user_id, bot, notification):
    import sqlite3
    conn = sqlite3.connect("family_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT relative_id FROM relatives WHERE senior_id = ?", (family_id,))
    relatives = [r[0] for r in cursor.fetchall()]
    if family_id != exclude_user_id:
        relatives.append(family_id)
    conn.close()
    for mid in relatives:
        try:
            await bot.send_message(mid, notification, parse_mode="Markdown")
        except:
            pass

async def handle_sos(update, context):
    user = update.effective_user
    lang = await get_user_lang(update)
    log_activity(user.id, "sos")
    await update.message.reply_text(get_text(lang, 'sos_sent'))
    user_name = context.user_data.get("name") or user.first_name
    for rel_id in get_relatives_for_senior(user.id):
        try:
            await context.bot.send_message(rel_id, f"🚨 {user_name} нажал SOS!")
        except:
            pass
    family_id = get_family_id_for_user(user.id)
    if family_id:
        add_to_family_feed(family_id, user.id, user_name, "SOS", "sos")
        await notify_family_members(family_id, user.id, context.bot, f"🚨 *{user_name}* нажал SOS!")

async def handle_family(update, context):
    user_id = update.effective_user.id
    summary = get_activity_summary(user_id)
    await update.message.reply_text(f"📊 Активность за 24ч:\n💬 {summary['talk']}\n💊 {summary['reminder_done']}\n🆘 {summary['sos']}")

async def handle_settings(update, context):
    await update.message.reply_text("Используйте /help для списка команд.")

async def fallback_text(update, context):
    await handle_talk(update, context)

# ---------- НАПОМИНАНИЯ О ЛЕКАРСТВАХ ----------
async def add_meds_start(update, context):
    await update.message.reply_text("Время (ЧЧ:ММ):", reply_markup=ReplyKeyboardRemove())
    return MedsState.ASK_TIME.value

async def add_meds_time(update, context):
    parts = update.message.text.split(":")
    if len(parts)!=2 or not parts[0].isdigit() or not parts[1].isdigit():
        await update.message.reply_text("Неверный формат.")
        return MedsState.ASK_TIME.value
    h,m = int(parts[0]), int(parts[1])
    if not (0<=h<=23 and 0<=m<=59):
        await update.message.reply_text("Часы 0-23, минуты 0-59.")
        return MedsState.ASK_TIME.value
    context.user_data["meds_time"] = f"{h:02d}:{m:02d}"
    await update.message.reply_text("Что напоминать?")
    return MedsState.ASK_TEXT.value

async def meds_reminder_job(context):
    job = context.job
    await context.bot.send_message(job.chat_id, text=f"💊 {job.data['text']}")
    log_activity(job.chat_id, "reminder_done")

async def add_meds_text(update, context):
    user_id = update.effective_user.id
    meds_time = context.user_data.get("meds_time")
    text = update.message.text.strip() or "Принять лекарство"
    add_reminder(user_id, "meds", text, meds_time)
    job_queue = context.job_queue
    h,m = map(int, meds_time.split(":"))
    job_queue.run_daily(meds_reminder_job, time=time(hour=h, minute=m), chat_id=user_id, data={"text": text})
    await update.message.reply_text(f"Напоминание на {meds_time} добавлено.", reply_markup=get_main_menu_keyboard(await get_user_lang(update), is_premium(user_id)))
    return ConversationHandler.END

async def meds_cancel(update, context):
    await update.message.reply_text("Отменено.", reply_markup=get_main_menu_keyboard(await get_user_lang(update), is_premium(update.effective_user.id)))
    return ConversationHandler.END

# ---------- ЕЖЕДНЕВНЫЙ ОПРОС ----------
async def daily_checkin(context):
    await context.bot.send_message(context.job.chat_id, "Как вы себя чувствуете? 🌷")

async def enable_checkin(update, context):
    chat_id = update.effective_chat.id
    job_queue = context.job_queue
    for job in job_queue.get_jobs_by_name(f"checkin-{chat_id}"):
        job.schedule_removal()
    job_queue.run_daily(daily_checkin, time=time(hour=10, minute=0), chat_id=chat_id, name=f"checkin-{chat_id}")
    await update.message.reply_text("Ежедневный опрос включён в 10:00.")

async def disable_checkin(update, context):
    chat_id = update.effective_chat.id
    for job in context.job_queue.get_jobs_by_name(f"checkin-{chat_id}"):
        job.schedule_removal()
    await update.message.reply_text("Опрос отключён.")

# ---------- ПРИВЯЗКА РОДСТВЕННИКА ----------
async def add_relative_cmd(update, context):
    if not context.args:
        await update.message.reply_text("/add_relative <ID>")
        return
    try:
        senior_id = int(context.args[0])
    except:
        await update.message.reply_text("ID должен быть числом.")
        return
    add_relative_link(senior_id, update.effective_user.id)
    await update.message.reply_text("Родственник привязан.")

# ---------- СЕМЕЙНАЯ ЛЕНТА ----------
async def family_send(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'))
        return
    if not context.args:
        await update.message.reply_text("/family_send <текст>")
        return
    msg = " ".join(context.args)
    user_name = context.user_data.get("name") or update.effective_user.first_name
    add_to_family_feed(family_id, user_id, user_name, msg)
    await notify_family_members(family_id, user_id, context.bot, f"📢 {user_name}: {msg}")
    await update.message.reply_text("Отправлено.")

async def family_feed(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text(get_text(lang, 'not_relative'))
        return
    feed = get_family_feed(family_id, limit=10)
    if not feed:
        await update.message.reply_text(get_text(lang, 'family_feed_empty'))
        return
    lines = ["📋 Семейная лента:"]
    for entry in feed:
        lines.append(f"{entry['author_name']} ({entry['created_at'][:16]}): {entry['message']}")
    await update.message.reply_text("\n".join(lines))

# ---------- КАЛЕНДАРЬ СОБЫТИЙ ----------
async def add_event_start(update, context):
    await update.message.reply_text("Дата ГГГГ-ММ-ДД:")
    return EventState.DATE.value
async def add_event_date(update, context):
    date_str = update.message.text.strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        await update.message.reply_text("Неверный формат.")
        return EventState.DATE.value
    context.user_data["event_date"] = date_str
    await update.message.reply_text("Время ЧЧ:ММ или - :")
    return EventState.TIME.value
async def add_event_time(update, context):
    t = update.message.text.strip()
    context.user_data["event_time"] = None if t=="-" else t
    await update.message.reply_text("Название:")
    return EventState.TITLE.value
async def add_event_title(update, context):
    context.user_data["event_title"] = update.message.text.strip()
    await update.message.reply_text("Описание или - :")
    return EventState.DESCRIPTION.value
async def add_event_description(update, context):
    desc = update.message.text.strip()
    context.user_data["event_description"] = None if desc=="-" else desc
    await update.message.reply_text("Тип: 1-ДР,2-Праздник,3-Встреча,4-Другое,5-ДР другого")
    return EventState.TYPE.value
async def add_event_type(update, context):
    choice = update.message.text.strip()
    type_map = {"1":"birthday","2":"holiday","3":"meeting","4":"other","5":"birthday"}
    if choice not in type_map:
        await update.message.reply_text("Выберите 1-5.")
        return EventState.TYPE.value
    context.user_data["event_type"] = type_map[choice]
    if choice=="5":
        await update.message.reply_text("ID именинника или - :")
        return EventState.TARGET_USER.value
    else:
        context.user_data["target_user_id"] = None
        await update.message.reply_text("За сколько дней напомнить? (число)")
        return EventState.REMIND_DAYS.value
async def add_event_target_user(update, context):
    t = update.message.text.strip()
    context.user_data["target_user_id"] = None if t=="-" else int(t)
    await update.message.reply_text("За сколько дней напомнить?")
    return EventState.REMIND_DAYS.value
async def add_event_remind_days(update, context):
    days = int(update.message.text.strip()) if update.message.text.strip().isdigit() else 1
    user_id = update.effective_user.id
    add_event(
        user_id=user_id,
        event_date=context.user_data["event_date"],
        title=context.user_data["event_title"],
        description=context.user_data.get("event_description"),
        event_time=context.user_data.get("event_time"),
        event_type=context.user_data.get("event_type","other"),
        remind_before_days=days,
        target_user_id=context.user_data.get("target_user_id")
    )
    await update.message.reply_text("Событие добавлено!", reply_markup=get_main_menu_keyboard(await get_user_lang(update), is_premium(user_id)))
    return -1

async def events_list(update, context):
    user_id = update.effective_user.id
    today = date.today().isoformat()
    events = get_events_for_user(user_id, from_date=today, limit=20)
    if not events:
        await update.message.reply_text("Нет событий.")
        return
    lines = ["📅 Ближайшие события:"]
    for ev in events:
        lines.append(f"{ev['date']} {ev['time'] or ''}: {ev['title']}")
    await update.message.reply_text("\n".join(lines))

async def delete_event_cmd(update, context):
    if not context.args:
        await update.message.reply_text("/delete_event <id>")
        return
    try:
        eid = int(context.args[0])
    except:
        await update.message.reply_text("ID число.")
        return
    if delete_event(eid, update.effective_user.id):
        await update.message.reply_text("Удалено.")
    else:
        await update.message.reply_text("Не найдено.")

# ---------- АНАЛИТИКА ----------
async def health_report(update, context):
    user_id = update.effective_user.id
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
        if days > 30:
            days = 30
    stats = get_user_stats(user_id, days)
    reminder_stats = get_reminder_completion_rate(user_id, days)
    if reminder_stats['total_reminders'] > 0:
        report = f"📊 *Отчёт о здоровье за {days} дней*\n💬 Разговоров: {stats['talks']}\n💊 Приёмов лекарств: {stats['reminders_done']}\n📈 Процент выполнения: {reminder_stats['completion_rate']:.1f}%\n🆘 SOS: {stats['sos']}\n🎤 Голосовых: {stats['voice']}\n🏆 Всего активностей: {stats['total']}"
    else:
        report = f"📊 *Отчёт о здоровье за {days} дней*\n💬 Разговоров: {stats['talks']}\n💊 Приёмов лекарств: {stats['reminders_done']}\n🆘 SOS: {stats['sos']}\n🎤 Голосовых: {stats['voice']}\n🏆 Всего активностей: {stats['total']}"
    if reminder_stats['completion_rate'] < 50 and reminder_stats['total_reminders'] > 0:
        report += "\n⚠️ Старайтесь не пропускать лекарства!"
    if stats['talks'] == 0:
        report += "\n💡 Общайтесь с ботом – это полезно!"
    await update.message.reply_text(report, parse_mode="Markdown")

async def family_report(update, context):
    user_id = update.effective_user.id
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("Вы не привязаны к семье.")
        return
    days = 7
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
        if days > 30:
            days = 30
    members = get_family_stats(family_id, days)
    report = f"👨‍👩‍👧 *Семейный отчёт за {days} дней*\n"
    total_talks = total_reminders = total_sos = 0
    for m in members:
        report += f"👤 {m['name']}\n   💬 {m['talks']}   💊 {m['reminders_done']}   🆘 {m['sos']}\n"
        total_talks += m['talks']; total_reminders += m['reminders_done']; total_sos += m['sos']
    report += f"📊 *Общая активность:* 💬 {total_talks}   💊 {total_reminders}   🆘 {total_sos}"
    await update.message.reply_text(report, parse_mode="Markdown")

async def member_stats(update, context):
    user_id = update.effective_user.id
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("Вы не привязаны к семье.")
        return
    if not context.args:
        await update.message.reply_text("/member_stats <ID> [дни]")
        return
    try:
        target_id = int(context.args[0])
    except:
        await update.message.reply_text("ID число.")
        return
    # проверим, что target_id член семьи
    import sqlite3
    conn = sqlite3.connect("family_bot.db")
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM relatives WHERE senior_id=? AND relative_id=?", (family_id, target_id))
    ok = cur.fetchone() is not None
    conn.close()
    if target_id != family_id and not ok:
        await update.message.reply_text("Не член семьи.")
        return
    days = 7
    if len(context.args)>1 and context.args[1].isdigit():
        days = int(context.args[1])
        if days>30: days=30
    stats = get_user_stats(target_id, days)
    user_info = get_user(target_id)
    name = user_info['name'] if user_info else f"User_{target_id}"
    await update.message.reply_text(f"📊 *{name}* (ID:{target_id}) за {days} дней:\n💬 {stats['talks']}\n💊 {stats['reminders_done']}\n🆘 {stats['sos']}\n🎤 {stats['voice']}\n🏆 Всего: {stats['total']}", parse_mode="Markdown")

# ---------- ИГРЫ ----------
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

async def games_menu(update, context):
    lang = await get_user_lang(update)
    await update.message.reply_text("🎮 *Игры*", reply_markup=get_games_menu_keyboard(lang), parse_mode="Markdown")

async def play_riddle(update, context):
    user_id = update.effective_user.id
    r = random.choice(RIDDLES)
    save_game_state(user_id, "riddle", json.dumps({"q": r[0], "a": r[1]}))
    await update.message.reply_text(f"🔮 *Загадка:*\n{r[0]}", parse_mode="Markdown")

async def play_words(update, context):
    user_id = update.effective_user.id
    save_game_state(user_id, "words", json.dumps({"last": None, "used": []}))
    await update.message.reply_text("📖 *Игра «Слова»*\nНапишите слово (существительное, ед.ч.):", parse_mode="Markdown")

async def play_truth_or_lie(update, context):
    user_id = update.effective_user.id
    q,a = random.choice(TRUTH_OR_LIE)
    save_game_state(user_id, "truth", json.dumps({"q": q, "a": a}))
    await update.message.reply_text(f"✅ *Правда или ложь?*\n{q}\nОтветьте «правда» или «ложь».", parse_mode="Markdown")

async def exit_game(update, context):
    clear_game_state(update.effective_user.id)
    await update.message.reply_text("❌ Вы вышли из игры.")

def find_word_on_letter(letter, used):
    words = ["апельсин","банан","вишня","груша","дыня","ежевика","жёлудь","земляника","ирис","йогурт","клубника","лимон","малина","нос","обезьяна","помидор","рис","самолёт","телефон","улитка","фонарь","хлеб","цветок","чайник","шапка","щёголь","эскимо","юбка","яблоко"]
    for w in words:
        if w[0]==letter and w not in used:
            return w
    return None

async def handle_game_answer(update, context):
    uid = update.effective_user.id
    state = get_game_state(uid)
    if not state:
        return
    game = state["game_name"]
    data = json.loads(state["game_data"])
    ans = update.message.text.strip().lower()
    if game == "riddle":
        correct = data["a"]
        if ans == correct or ans in correct:
            await update.message.reply_text("🎉 Правильно!")
        else:
            await update.message.reply_text(f"❌ Неправильно! Ответ: {correct}")
        clear_game_state(uid)
    elif game == "truth":
        correct = data["a"]
        user_true = ans in ["правда","верно","да","true"]
        user_false = ans in ["ложь","неправда","нет","false"]
        if (user_true and correct) or (user_false and not correct):
            await update.message.reply_text("🎉 Правильно!")
        else:
            await update.message.reply_text(f"❌ Неправильно! Это {'правда' if correct else 'ложь'}.")
        clear_game_state(uid)
    elif game == "words":
        last = data.get("last")
        used = set(data.get("used", []))
        if ans in used:
            await update.message.reply_text(f"❌ Слово «{ans}» уже было. Вы проиграли.")
            clear_game_state(uid)
            return
        if last and ans[0] != last:
            await update.message.reply_text(f"❌ Слово должно начинаться на букву «{last}». Вы проиграли.")
            clear_game_state(uid)
            return
        if len(ans) < 2:
            await update.message.reply_text("❌ Слишком короткое слово. Вы проиграли.")
            clear_game_state(uid)
            return
        used.add(ans)
        new_last = ans[-1]
        bot_word = find_word_on_letter(new_last, used)
        if bot_word:
            used.add(bot_word)
            save_game_state(uid, "words", json.dumps({"last": bot_word[-1], "used": list(used)}))
            await update.message.reply_text(f"🤖 Моё слово: {bot_word}\nВаша очередь на букву '{bot_word[-1]}'")
        else:
            await update.message.reply_text(f"🎉 Я не могу найти слово на букву '{new_last}'! Вы победили!")
            clear_game_state(uid)

# ---------- ГОЛОСОВЫЕ СООБЩЕНИЯ ----------
async def handle_voice(update, context):
    user = update.effective_user
    user_id = user.id
    lang = await get_user_lang(update)
    name = context.user_data.get("name") or user.first_name
    processing = await update.message.reply_text("🎤 Слушаю...")
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        audio = AudioSegment.from_ogg(io.BytesIO(audio_bytes))
        audio = audio.set_channels(1).set_frame_rate(16000)
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_io.seek(0)
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as src:
            recognizer.adjust_for_ambient_noise(src, duration=0.5)
            audio_data = recognizer.record(src)
        recognized = None
        try:
            recognized = recognizer.recognize_google(audio_data, language="ru-RU")
        except:
            try:
                recognized = recognizer.recognize_google(audio_data, language="en-US")
            except:
                pass
        if not recognized:
            await processing.edit_text("😔 Не удалось распознать голос.")
            return
        await processing.edit_text(f"📝 Вы сказали: *{recognized}*\n🤔 Думаю...", parse_mode="Markdown")
        reply = await generate_companion_reply(recognized, name=name, user_id=user_id)
        await processing.delete()
        await update.message.reply_text(reply, reply_markup=get_main_menu_keyboard(lang, is_premium(user_id)))
        log_activity(user_id, "voice")
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await processing.edit_text("❌ Ошибка обработки голоса.")

# ---------- МЕДИАФАЙЛЫ ----------
async def handle_photo(update, context):
    user = update.effective_user
    user_id = user.id
    user_name = context.user_data.get("name") or user.first_name
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("Вы не привязаны к семье.")
        return
    photo = update.message.photo[-1]
    caption = update.message.caption or ""
    save_media(family_id, user_id, user_name, "photo", photo.file_id, caption)
    await update.message.reply_text("📸 Фото добавлено в семейный альбом!")

async def handle_video(update, context):
    user = update.effective_user
    user_id = user.id
    user_name = context.user_data.get("name") or user.first_name
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("Вы не привязаны к семье.")
        return
    video = update.message.video
    caption = update.message.caption or ""
    save_media(family_id, user_id, user_name, "video", video.file_id, caption)
    await update.message.reply_text("🎥 Видео добавлено в семейный альбом!")

async def show_album(update, context):
    user_id = update.effective_user.id
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("Вы не привязаны к семье.")
        return
    media = get_family_media(family_id, limit=10)
    if not media:
        await update.message.reply_text("Альбом пуст.")
        return
    for m in media:
        caption = f"📅 {str(m['date'])[:16]}\n👤 {m['author']}"
        if m['caption']:
            caption += f"\n💬 {m['caption']}"
        if m['type'] == 'photo':
            await update.message.reply_photo(photo=m['file_id'], caption=caption)
        else:
            await update.message.reply_video(video=m['file_id'], caption=caption)

# ---------- МЕДИЦИНСКИЙ ДНЕВНИК ----------
async def health_menu(update, context):
    lang = await get_user_lang(update)
    premium = is_premium(update.effective_user.id)
    keyboard = [["📝 Добавить запись", "📊 Статистика"], ["📋 Мои записи", "📈 Графики"], ["🔙 Назад"]]
    await update.message.reply_text("🏥 *Медицинский дневник*", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode="Markdown")
    return HealthState.CHOOSE.value

async def health_menu_router(update, context):
    text = update.message.text
    if text in ["📝 Добавить запись", "📝 Add record"]:
        await update.message.reply_text("Дата ГГГГ-ММ-ДД:")
        return HealthState.DATE.value
    elif text in ["📊 Статистика", "📊 Statistics"]:
        await health_stats(update, context)
        return -1
    elif text in ["📋 Мои записи", "📋 My records"]:
        await health_list(update, context)
        return -1
    elif text in ["📈 Графики", "📈 Charts"]:
        if not is_premium(update.effective_user.id):
            await update.message.reply_text("⭐ Только премиум.")
        else:
            await health_chart(update, context)
        return -1
    elif text in ["🔙 Назад", "🔙 Back"]:
        await update.message.reply_text("Назад", reply_markup=get_main_menu_keyboard(await get_user_lang(update), is_premium(update.effective_user.id)))
        return -1
    return -1

async def health_add_date(update, context):
    date_str = update.message.text.strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        await update.message.reply_text("Неверный формат.")
        return HealthState.DATE.value
    context.user_data["health_date"] = date_str
    await update.message.reply_text("Время ЧЧ:ММ или - :")
    return HealthState.TIME.value
async def health_add_time(update, context):
    t = update.message.text.strip()
    context.user_data["health_time"] = None if t=="-" else t
    await update.message.reply_text("Верхнее давление (систолическое) или - :")
    return HealthState.SYSTOLIC.value
async def health_add_systolic(update, context):
    val = update.message.text.strip()
    context.user_data["health_systolic"] = None if val=="-" else int(val)
    await update.message.reply_text("Нижнее давление (диастолическое) или - :")
    return HealthState.DIASTOLIC.value
async def health_add_diastolic(update, context):
    val = update.message.text.strip()
    context.user_data["health_diastolic"] = None if val=="-" else int(val)
    await update.message.reply_text("Пульс или - :")
    return HealthState.PULSE.value
async def health_add_pulse(update, context):
    val = update.message.text.strip()
    context.user_data["health_pulse"] = None if val=="-" else int(val)
    await update.message.reply_text("Сахар (ммоль/л) или - :")
    return HealthState.SUGAR.value
async def health_add_sugar(update, context):
    val = update.message.text.strip()
    if val == "-":
        context.user_data["health_sugar"] = None
    else:
        try:
            context.user_data["health_sugar"] = float(val)
        except:
            await update.message.reply_text("Введите число.")
            return HealthState.SUGAR.value
    await update.message.reply_text("Вес (кг) или - :")
    return HealthState.WEIGHT.value
async def health_add_weight(update, context):
    val = update.message.text.strip()
    if val == "-":
        context.user_data["health_weight"] = None
    else:
        try:
            context.user_data["health_weight"] = float(val)
        except:
            await update.message.reply_text("Введите число.")
            return HealthState.WEIGHT.value
    await update.message.reply_text("Заметки (или - пропустить):")
    return HealthState.NOTES.value
async def health_add_notes(update, context):
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
    await update.message.reply_text("✅ Запись добавлена!", reply_markup=get_main_menu_keyboard(await get_user_lang(update), is_premium(user_id)))
    return -1

async def health_stats(update, context):
    user_id = update.effective_user.id
    stats = get_health_stats(user_id, days=30)
    if not stats or stats['records_count']==0:
        await update.message.reply_text("Нет записей.")
        return
    text = f"📊 *Статистика за 30 дней*\n💓 Давление: {stats['systolic_avg']:.0f}/{stats['diastolic_avg']:.0f} (ср)\n💗 Пульс: {stats['pulse_avg']:.0f}\n🩸 Сахар: {stats['sugar_avg']:.1f}\n⚖️ Вес: {stats['weight_avg']:.1f} кг\n📝 Всего записей: {stats['records_count']}"
    await update.message.reply_text(text, parse_mode="Markdown")

async def health_list(update, context):
    user_id = update.effective_user.id
    records = get_health_records(user_id, days=30)
    if not records:
        await update.message.reply_text("Нет записей.")
        return
    lines = ["📋 *Ваши записи*"]
    for r in records[:10]:
        line = f"{r['date']} {r['time'] or ''}: "
        if r['systolic'] and r['diastolic']:
            line += f"давление {r['systolic']}/{r['diastolic']} "
        if r['pulse']:
            line += f"пульс {r['pulse']} "
        if r['blood_sugar']:
            line += f"сахар {r['blood_sugar']} "
        if r['weight']:
            line += f"вес {r['weight']} кг"
        lines.append(line)
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def health_chart(update, context):
    user_id = update.effective_user.id
    if not is_premium(user_id):
        await update.message.reply_text("⭐ Только премиум.")
        return
    records = get_health_records(user_id, days=30)
    if not records:
        await update.message.reply_text("Нет данных.")
        return
    records_sorted = sorted(records, key=lambda x: x['date'])
    dates = [r['date'] for r in records_sorted]
    systolic = [r['systolic'] for r in records_sorted if r['systolic']]
    diastolic = [r['diastolic'] for r in records_sorted if r['diastolic']]
    if not systolic and not diastolic:
        await update.message.reply_text("Нет данных о давлении.")
        return
    try:
        import matplotlib.pyplot as plt
        import io
        plt.figure(figsize=(10,5))
        if systolic:
            plt.plot(dates, systolic, marker='o', label='Верхнее')
        if diastolic:
            plt.plot(dates, diastolic, marker='s', label='Нижнее')
        plt.xticks(rotation=45)
        plt.legend()
        plt.title('Динамика давления')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        await update.message.reply_photo(photo=buf, caption="📈 График давления")
        plt.close()
    except ImportError:
        await update.message.reply_text("⚠️ Для графиков нужна библиотека matplotlib.")

# ---------- ЭКСПОРТ (премиум) ----------
async def export_menu(update, context):
    lang = await get_user_lang(update)
    if not is_premium(update.effective_user.id):
        await update.message.reply_text(get_text(lang, 'premium_only'))
        return -1
    keyboard = [["📋 История диалогов", "🏥 Медицинские записи"], ["👨‍👩‍👧 Семейная лента", "🔙 Назад"]]
    await update.message.reply_text("📁 *Экспорт данных*", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode="Markdown")
    return ExportState.CHOOSE.value

async def export_choice(update, context):
    user_id = update.effective_user.id
    choice = update.message.text
    if choice in ["📋 История диалогов", "📋 Chat history"]:
        csv_data = export_chat_history(user_id)
        await update.message.reply_document(document=io.BytesIO(csv_data.encode('utf-8')), filename="chat.csv")
    elif choice in ["🏥 Медицинские записи", "🏥 Health records"]:
        csv_data = export_health_records(user_id)
        await update.message.reply_document(document=io.BytesIO(csv_data.encode('utf-8')), filename="health.csv")
    elif choice in ["👨‍👩‍👧 Семейная лента", "👨‍👩‍👧 Family feed"]:
        family_id = get_family_id_for_user(user_id)
        if family_id:
            csv_data = export_family_feed(family_id)
            await update.message.reply_document(document=io.BytesIO(csv_data.encode('utf-8')), filename="family.csv")
        else:
            await update.message.reply_text("Не привязаны к семье.")
    elif choice in ["🔙 Назад", "🔙 Back"]:
        await update.message.reply_text("Назад", reply_markup=get_main_menu_keyboard(await get_user_lang(update), is_premium(user_id)))
        return -1
    return -1

# ---------- БЮДЖЕТ (премиум) ----------
async def budget_menu(update, context):
    lang = await get_user_lang(update)
    if not is_premium(update.effective_user.id):
        await update.message.reply_text(get_text(lang, 'premium_only'))
        return -1
    keyboard = [["➕ Добавить транзакцию", "📊 Статистика"], ["📋 Список операций", "🏷️ Категории"], ["🔙 Назад"]]
    await update.message.reply_text(get_text(lang, 'budget_menu'), reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return BudgetState.CHOOSE.value

async def budget_menu_router(update, context):
    text = update.message.text
    if text in ["➕ Добавить транзакцию", "➕ Add"]:
        await update.message.reply_text("Тип: 1-Доход, 2-Расход")
        return BudgetState.TYPE.value
    elif text in ["📊 Статистика", "📊 Statistics"]:
        await budget_stats(update, context)
        return -1
    elif text in ["📋 Список операций", "📋 List"]:
        await budget_list(update, context)
        return -1
    elif text in ["🏷️ Категории", "🏷️ Categories"]:
        await budget_categories(update, context)
        return -1
    elif text in ["🔙 Назад", "🔙 Back"]:
        await update.message.reply_text("Назад", reply_markup=get_main_menu_keyboard(await get_user_lang(update), is_premium(update.effective_user.id)))
        return -1
    return -1

async def budget_add_type(update, context):
    choice = update.message.text.strip()
    if choice == "1":
        context.user_data["budget_type"] = "income"
    elif choice == "2":
        context.user_data["budget_type"] = "expense"
    else:
        await update.message.reply_text("Введите 1 или 2.")
        return BudgetState.TYPE.value
    categories = get_categories()
    cat_list = "\n".join([f"{c['name']} ({c['icon']})" for c in categories if c['type'] == context.user_data["budget_type"]])
    await update.message.reply_text(f"Категория:\n{cat_list}")
    return BudgetState.CATEGORY.value

async def budget_add_category(update, context):
    cat = update.message.text.strip()
    categories = get_categories()
    if not any(c['name'] == cat for c in categories if c['type'] == context.user_data["budget_type"]):
        await update.message.reply_text("Неверная категория.")
        return BudgetState.CATEGORY.value
    context.user_data["budget_category"] = cat
    await update.message.reply_text("Сумма (число):")
    return BudgetState.AMOUNT.value

async def budget_add_amount(update, context):
    try:
        amt = float(update.message.text.strip())
        if amt <= 0: raise ValueError
        context.user_data["budget_amount"] = amt
    except:
        await update.message.reply_text("Введите положительное число.")
        return BudgetState.AMOUNT.value
    await update.message.reply_text("Дата (ГГГГ-ММ-ДД) или - сегодня:")
    return BudgetState.DATE.value

async def budget_add_date(update, context):
    date_str = update.message.text.strip()
    if date_str == "-":
        date_str = date.today().isoformat()
    elif not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        await update.message.reply_text("Неверный формат.")
        return BudgetState.DATE.value
    context.user_data["budget_date"] = date_str
    await update.message.reply_text("Описание (или - пропустить):")
    return BudgetState.DESCRIPTION.value

async def budget_add_description(update, context):
    desc = update.message.text.strip()
    if desc == "-":
        desc = None
    user_id = update.effective_user.id
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("Вы не привязаны к семье.")
        return -1
    add_transaction(user_id, family_id, context.user_data["budget_amount"], context.user_data["budget_category"], context.user_data["budget_type"], context.user_data["budget_date"], desc)
    await update.message.reply_text(get_text(await get_user_lang(update), 'budget_add_success'), reply_markup=get_main_menu_keyboard(await get_user_lang(update), is_premium(user_id)))
    return -1

async def budget_stats(update, context):
    user_id = update.effective_user.id
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("Не привязаны к семье.")
        return
    summary = get_budget_summary(family_id)
    await update.message.reply_text(f"💰 Доходы: {summary['income']:.2f}\n📉 Расходы: {summary['expense']:.2f}\n💎 Баланс: {summary['balance']:.2f}")

async def budget_list(update, context):
    user_id = update.effective_user.id
    family_id = get_family_id_for_user(user_id)
    if not family_id:
        await update.message.reply_text("Не привязаны к семье.")
        return
    trans = get_transactions(family_id, limit=10)
    if not trans:
        await update.message.reply_text("Нет транзакций.")
        return
    lines = ["📋 Последние транзакции:"]
    for t in trans:
        sign = "+" if t['type']=='income' else "-"
        lines.append(f"{t['date']} {t['category']}: {sign}{t['amount']:.2f}")
    await update.message.reply_text("\n".join(lines))

async def budget_categories(update, context):
    cats = get_categories()
    text = "🏷️ *Категории бюджета:*\n" + "\n".join([f"{c['icon']} {c['name']} ({c['type']})" for c in cats])
    await update.message.reply_text(text, parse_mode="Markdown")

# ---------- ПРЕМИУМ ----------
async def premium_info(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    premium = is_premium(user_id)
    if premium:
        expiry = get_premium_expiry(user_id)
        status = get_text(lang, 'premium_active', date=expiry.strftime('%d.%m.%Y'))
    else:
        status = get_text(lang, 'premium_inactive')
    await update.message.reply_text(get_text(lang, 'premium_info', status=status), reply_markup=get_main_menu_keyboard(lang, premium))

async def activate_premium(update, context):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    if not context.args:
        await update.message.reply_text(get_text(lang, 'activate_usage'))
        return
    code = context.args[0].upper()
    if activate_code(code, user_id):
        await update.message.reply_text(get_text(lang, 'activate_success'), reply_markup=get_main_menu_keyboard(lang, True))
    else:
        await update.message.reply_text(get_text(lang, 'activate_fail'))

async def gen_premium_code(update, context):
    ADMIN_ID = 8091619207  # ЗАМЕНИТЕ НА СВОЙ TELEGRAM ID
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Недостаточно прав.")
        return
    if not context.args:
        await update.message.reply_text("/gen_code <дни>")
        return
    try:
        days = int(context.args[0])
        code = generate_code(days)
        await update.message.reply_text(f"Код: `{code}` на {days} дней", parse_mode="Markdown")
    except:
        await update.message.reply_text("Ошибка.")

# ---------- ПОГОДА ----------
async def weather_command(update, context):
    user = update.effective_user
    lang = await get_user_lang(update)
    name = context.user_data.get("name") or user.first_name
    city = context.user_data.get("city")
    if not city:
        await update.message.reply_text(f"{name}, скажите ваш город: «Я живу в Москве»")
        return
    summary = await get_weather_summary(city)
    if not summary:
        await update.message.reply_text("Не удалось получить погоду.")
        return
    await update.message.reply_text(f"🌤️ {summary}")

async def set_city(update, context):
    user_id = update.effective_user.id
    text = update.message.text.lower()
    match = re.search(r'(мой город|живу в|город)\s+([а-яА-ЯёЁa-zA-Z\s\-]+)', text)
    if match:
        city = match.group(2).strip().capitalize()
        if len(city) > 1:
            user = get_user(user_id) or {}
            upsert_user(user_id, role=user.get("role","senior"), name=user.get("name"), city=city)
            await update.message.reply_text(f"✅ Запомнила: {city}")
    else:
        await update.message.reply_text("Напишите: «Я живу в Москве»")

# ---------- ПРОЧИЕ КОМАНДЫ ----------
async def help_cmd(update, context):
    await update.message.reply_text(
        "🤖 *Бот-компаньон «Семья»*\n"
        "/start – регистрация\n"
        "/menu – главное меню\n"
        "/add_meds – напоминание о лекарствах\n"
        "/enable_checkin – ежедневный опрос\n"
        "/disable_checkin – отключить опрос\n"
        "/add_relative <ID> – привязать родственника\n"
        "/family_send <текст> – семейный чат\n"
        "/family_feed – лента\n"
        "/sos – экстренная помощь\n"
        "/weather – погода\n"
        "/add_event – добавить событие\n"
        "/events_list – список событий\n"
        "/health – медицинский дневник\n"
        "/health_report – отчёт о здоровье\n"
        "/family_report – семейная статистика\n"
        "/member_stats <ID> – статистика члена семьи\n"
        "/games – игры\n"
        "/album – семейный альбом\n"
        "/premium – информация о премиум\n"
        "/activate <код> – активировать премиум\n"
        "/help – эта справка", parse_mode="Markdown"
    )

async def menu_cmd(update, context):
    lang = await get_user_lang(update)
    premium = is_premium(update.effective_user.id)
    await update.message.reply_text("Меню", reply_markup=get_main_menu_keyboard(lang, premium))

async def lang_command(update, context):
    if not context.args:
        await update.message.reply_text("/lang ru или /lang en")
        return
    new = context.args[0].lower()
    if new not in ['ru','en']:
        await update.message.reply_text("Поддерживаются ru, en")
        return
    set_user_language(update.effective_user.id, new)
    await update.message.reply_text(f"Язык изменён на {new}")

async def clear_history_cmd(update, context):
    clear_chat_history(update.effective_user.id)
    await update.message.reply_text("История диалогов очищена.")

async def companions_cmd(update, context):
    await update.message.reply_text(social_companions_info())
async def volunteers_cmd(update, context):
    await update.message.reply_text(social_volunteers_info())
async def health_extra_cmd(update, context):
    await update.message.reply_text(health_extra_info())
async def helper_cmd(update, context):
    await update.message.reply_text(home_helper_info())
async def nostalgia_cmd(update, context):
    await update.message.reply_text(nostalgia_menu_text())
async def courses_cmd(update, context):
    await update.message.reply_text(courses_menu_text())
async def achievements_cmd(update, context):
    await update.message.reply_text(achievements_text())
async def admin_analytics_cmd(update, context):
    await update.message.reply_text(analytics_info_text())
async def voice_help(update, context):
    await update.message.reply_text(voice_interface_info())

# ---------- ЕЖЕДНЕВНЫЕ ЗАДАЧИ ----------
async def send_birthday_greetings(context):
    today = date.today().isoformat()
    birthdays = get_birthdays_for_date(today)
    for b in birthdays:
        uid = b['target_user_id'] if b['target_user_id'] else b['user_id']
        user_info = get_user(uid)
        name = user_info['name'] if user_info else f"User_{uid}"
        await context.bot.send_message(uid, f"🎉 С днём рождения, {name}! 🎂")
        family_id = get_family_id_for_user(uid)
        if family_id:
            add_to_family_feed(family_id, 0, "Бот", f"🎉 Сегодня день рождения {name}!", "birthday")
            await notify_family_members(family_id, uid, context.bot, f"🎉 Сегодня день рождения {name}!")

# ---------- ПОСТРОЕНИЕ ПРИЛОЖЕНИЯ ----------
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
    request = HTTPXRequest(connect_timeout=settings.telegram_connect_timeout, read_timeout=settings.telegram_read_timeout, write_timeout=settings.telegram_read_timeout, proxy=settings.telegram_proxy)
    builder = builder.request(request)
    application = builder.build()

    # Онбординг
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

    # Напоминания
    meds_conv = ConversationHandler(
        entry_points=[CommandHandler("add_meds", add_meds_start)],
        states={
            MedsState.ASK_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_time)],
            MedsState.ASK_TEXT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_text)],
        },
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(meds_conv)

    # Календарь
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

    # Медицинский дневник
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

    # Экспорт
    export_conv = ConversationHandler(
        entry_points=[CommandHandler("export", export_menu)],
        states={ExportState.CHOOSE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, export_choice)]},
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(export_conv)

    # Бюджет
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

    # Аналитика
    application.add_handler(CommandHandler("health_report", health_report))
    application.add_handler(CommandHandler("family_report", family_report))
    application.add_handler(CommandHandler("member_stats", member_stats))

    # Игры
    application.add_handler(CommandHandler("games", games_menu))
    application.add_handler(MessageHandler(filters.Regex("^🔮 Загадка$"), play_riddle))
    application.add_handler(MessageHandler(filters.Regex("^📖 Слова$"), play_words))
    application.add_handler(MessageHandler(filters.Regex("^✅ Правда или ложь$"), play_truth_or_lie))
    application.add_handler(MessageHandler(filters.Regex("^❌ Выйти из игры$"), exit_game))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_game_answer), group=1)

    # Голос, медиа
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(CommandHandler("album", show_album))

    # Основные команды
    application.add_handler(CommandHandler("enable_checkin", enable_checkin))
    application.add_handler(CommandHandler("disable_checkin", disable_checkin))
    application.add_handler(CommandHandler("add_relative", add_relative_cmd))
    application.add_handler(CommandHandler("family_send", family_send))
    application.add_handler(CommandHandler("family_feed", family_feed))
    application.add_handler(CommandHandler("events_list", events_list))
    application.add_handler(CommandHandler("delete_event", delete_event_cmd))
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("premium", premium_info))
    application.add_handler(CommandHandler("activate", activate_premium))
    application.add_handler(CommandHandler("gen_code", gen_premium_code))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("menu", menu_cmd))
    application.add_handler(CommandHandler("lang", lang_command))
    application.add_handler(CommandHandler("clear_history", clear_history_cmd))

    for cmd in [companions_cmd, volunteers_cmd, health_extra_cmd, helper_cmd, nostalgia_cmd, courses_cmd, achievements_cmd, admin_analytics_cmd, voice_help]:
        application.add_handler(CommandHandler(cmd.__name__.replace("_cmd", ""), cmd))

    # Город
    application.add_handler(MessageHandler(filters.Regex(r'(мой город|живу в|город)'), set_city))

    # Главный роутер
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_router), group=2)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text), group=3)

    # JobQueue
    job_queue = application.job_queue
    if job_queue:
        async def daily_event_reminder(context):
            today = date.today()
            for ev in get_events_by_date(today.isoformat()):
                await context.bot.send_message(ev['user_id'], f"🔔 Напоминание: {ev['title']}")
            tomorrow = (today + timedelta(days=1)).isoformat()
            for ev in get_events_by_date(tomorrow):
                if ev['remind_before_days'] >= 1:
                    await context.bot.send_message(ev['user_id'], f"📅 Завтра событие: {ev['title']}")
        job_queue.run_daily(daily_event_reminder, time=time(hour=9, minute=0))
        job_queue.run_daily(send_birthday_greetings, time=time(hour=9, minute=5))

    return application

def run_telegram():
    settings = get_settings()
    logger.info("Starting bot...")
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
    loop.run_until_complete(start_bot())

def main():
    tg_thread = threading.Thread(target=run_telegram, daemon=True)
    tg_thread.start()
    run_flask()

if __name__ == "__main__":
    main()
