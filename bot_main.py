from __future__ import annotations

import os
import re
import logging
import sys
import sqlite3
import aiohttp
import asyncio
from enum import Enum, auto
from typing import Final, Optional
from datetime import time, datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Voice,
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
from storage import (
    init_db,
    upsert_user,
    list_reminders,
    add_reminder,
    log_activity,
    get_activity_summary,
    add_relative_link,
    get_relatives_for_senior,
)
from ai_service import ai_service
from voice_processor import voice_processor

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

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
    ],
    resize_keyboard=True,
)

# ==================== ПОГОДА ====================

async def get_weather_async(city: str) -> str:
    api_key = os.environ.get("OPENWEATHER_API_KEY", "")
    if not api_key:
        return None
    
    city_normalized = city.strip().lower().replace("ё", "е")
    
    city_map = {
        "москва": "Moscow", "санкт-петербург": "Saint Petersburg",
        "новосибирск": "Novosibirsk", "екатеринбург": "Yekaterinburg",
        "казань": "Kazan", "нижний новгород": "Nizhny Novgorod",
        "краснодар": "Krasnodar", "сочи": "Sochi",
    }
    
    variants = [city]
    if city_normalized in city_map:
        variants.append(city_map[city_normalized])
    
    for try_city in variants:
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?q={try_city}&appid={api_key}&units=metric&lang=ru"
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json()
                        temp = round(data['main']['temp'])
                        feels_like = round(data['main']['feels_like'])
                        humidity = data['main']['humidity']
                        wind_speed = data['wind']['speed']
                        description = data['weather'][0]['description']
                        city_name = data['name']
                        
                        emoji = "🌡️"
                        if "ясно" in description or "солнечно" in description:
                            emoji = "☀️"
                        elif "облачно" in description or "пасмурно" in description:
                            emoji = "☁️"
                        elif "дождь" in description:
                            emoji = "🌧️"
                        elif "снег" in description:
                            emoji = "❄️"
                        elif "гроза" in description:
                            emoji = "⛈️"
                        
                        return (f"{emoji} **Погода в {city_name}**\n\n"
                               f"🌡️ Температура: **{temp}°C**\n"
                               f"🤔 Ощущается как: **{feels_like}°C**\n"
                               f"💧 Влажность: **{humidity}%**\n"
                               f"💨 Ветер: **{wind_speed} м/с**\n"
                               f"📖 Описание: **{description.capitalize()}**")
        except Exception:
            continue
    return None

# ==================== ОНБОРДИНГ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = ("Здравствуйте! Я бот-компаньон «Семья» 🏡\n\n"
            "Давайте познакомимся.\nКто вы?\n\n➤ Я пожилой пользователь\n➤ Я родственник/опекун")
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
        await update.message.reply_text("Хорошо! Вы родственник.\nВведите код привязки.", reply_markup=ReplyKeyboardRemove())
        return OnboardingState.RELATIVE_CODE.value
    context.user_data["role"] = Role.SENIOR.value
    await update.message.reply_text("Рада знакомству! 🌷 Как вас зовут?", reply_markup=ReplyKeyboardRemove())
    return OnboardingState.SENIOR_NAME.value

async def senior_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = (update.message.text or "").strip()
    await update.message.reply_text(f"Очень приятно, {context.user_data['name']}!\n\nСколько вам лет?")
    return OnboardingState.SENIOR_AGE.value

async def senior_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text("Пожалуйста, введите число.")
        return OnboardingState.SENIOR_AGE.value
    context.user_data["age"] = int(text)
    await update.message.reply_text("В каком городе вы живёте?")
    return OnboardingState.SENIOR_CITY.value

async def senior_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["city"] = (update.message.text or "").strip()
    await update.message.reply_text("Отлично!\n\nРасскажите, чем вы любите заниматься?")
    return OnboardingState.SENIOR_INTERESTS.value

async def senior_interests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["interests"] = (update.message.text or "").strip()
    user = update.effective_user
    telegram_id = user.id if user else 0
    upsert_user(
        telegram_id=telegram_id,
        role=context.user_data.get("role", Role.SENIOR.value),
        name=context.user_data.get("name"),
        age=context.user_data.get("age"),
        city=context.user_data.get("city"),
        interests=context.user_data.get("interests"),
    )
    name_for_text = context.user_data.get("name") or "друг"
    await update.message.reply_text(f"Спасибо, {name_for_text}! Я всё запомнила.\n\nВот главное меню:", reply_markup=MAIN_MENU_KEYBOARD)
    return ConversationHandler.END

async def relative_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    upsert_user(telegram_id=user.id if user else 0, role=Role.RELATIVE.value, name=user.first_name if user else None)
    await update.message.reply_text("Спасибо! Код принят.\n\nВот главное меню:", reply_markup=MAIN_MENU_KEYBOARD)
    return ConversationHandler.END

# ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ====================

async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if text.startswith("💬"):
        await handle_talk(update, context)
    elif text.startswith("📅"):
        await handle_reminders(update, context)
    elif text.startswith("👥"):
        await handle_events(update, context)
    elif text.startswith("🆘"):
        await handle_sos(update, context)
    elif text.startswith("👨‍👩‍👧"):
        await handle_family(update, context)
    elif text.startswith("⚙️"):
        await handle_settings(update, context)
    else:
        await handle_talk(update, context)

async def handle_talk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    user_message = (update.message.text or "").strip()
    
    if user_message and user_message[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️"]:
        user_message = user_message[1:].strip()
        if not user_message:
            await update.message.reply_text("Напишите мне что-нибудь! 😊", reply_markup=MAIN_MENU_KEYBOARD)
            return
    if user:
        log_activity(user.id, "talk")
    
    msg_lower = user_message.lower()
    
    if any(w in msg_lower for w in ['погод', 'прогноз', 'дождь', 'ветер', 'температура']):
        city = context.user_data.get("city")
        if not city:
            await update.message.reply_text("🌤️ Скажите ваш город, например: «Я живу в Москве»", reply_markup=MAIN_MENU_KEYBOARD)
            return
        loading = await update.message.reply_text("🌤️ Узнаю погоду...")
        weather = await get_weather_async(city)
        await loading.delete()
        if weather:
            await update.message.reply_text(weather, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
        else:
            await update.message.reply_text(f"😔 Не найдено: {city}", reply_markup=MAIN_MENU_KEYBOARD)
        return
    
    if any(w in msg_lower for w in ['время', 'часы', 'который час', 'дата', 'сегодня']):
        now = datetime.now()
        await update.message.reply_text(f"📅 {now.strftime('%d.%m.%Y')}\n🕐 {now.strftime('%H:%M')}", reply_markup=MAIN_MENU_KEYBOARD)
        return
    
    if any(w in msg_lower for w in ['привет', 'здравствуй', 'доброе утро', 'добрый день']):
        await update.message.reply_text(f"Здравствуйте, {name}! 🌷\n\nЧем могу помочь?", reply_markup=MAIN_MENU_KEYBOARD)
        return
    
    if any(w in msg_lower for w in ['как дела', 'как ты', 'как поживаешь']):
        await update.message.reply_text(f"У меня всё отлично, {name}! 😊 А как вы?", reply_markup=MAIN_MENU_KEYBOARD)
        return
    
    if any(w in msg_lower for w in ['помощь', 'help', 'что умеешь', 'команды']):
        await update.message.reply_text(
            f"🤖 **Что я умею, {name}:**\n\n"
            f"• 🌤️ **Погода** — «какая погода»\n"
            f"• 🎤 **Голосовые** — отправьте голосовое\n"
            f"• 💊 **Напоминания** — /add_meds\n"
            f"• 👨‍👩‍👧 **Семья** — кнопка в меню\n"
            f"• 🆘 **SOS** — экстренная помощь\n"
            f"• 🕐 **Время** — «который час»",
            parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD
        )
        return
    
    if any(w in msg_lower for w in ['спасибо', 'благодарю']):
        await update.message.reply_text(f"Пожалуйста, {name}! 😊", reply_markup=MAIN_MENU_KEYBOARD)
        return
    
    thinking = await update.message.reply_text("🤔 Думаю...")
    try:
        reply = await ai_service.generate_response(message=user_message, user_id=user.id if user else 0, user_name=name)
        await thinking.delete()
        await update.message.reply_text(reply, reply_markup=MAIN_MENU_KEYBOARD)
    except Exception as e:
        await thinking.delete()
        await update.message.reply_text(f"Извините, {name}, ошибка. Попробуйте ещё раз! 😊", reply_markup=MAIN_MENU_KEYBOARD)

# ==================== ГОЛОСОВЫЕ СООБЩЕНИЯ ====================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    voice = update.message.voice
    if not voice:
        return
    
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    processing_msg = await update.message.reply_text("🎤 Обрабатываю голосовое сообщение...\n\nЭто может занять до 30 секунд.")
    
    try:
        logger.info(f"Voice from user, duration: {voice.duration}s")
        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        logger.info(f"Downloaded {len(audio_bytes)} bytes")
        
        if not voice_processor.available:
            await processing_msg.edit_text("❌ Голосовой помощник недоступен.\n\nПожалуйста, напишите текстом.", reply_markup=MAIN_MENU_KEYBOARD)
            return
        
        recognized_text = await voice_processor.process_voice(bytes(audio_bytes))
        logger.info(f"Recognized: '{recognized_text}'")
        
        if recognized_text:
            await processing_msg.edit_text(f"📝 Вы сказали:\n\n*\"{recognized_text}\"*\n\n🤔 Думаю над ответом...", parse_mode="Markdown")
            reply = await ai_service.generate_response(message=recognized_text, user_id=user.id if user else 0, user_name=name)
            await processing_msg.delete()
            await update.message.reply_text(reply, reply_markup=MAIN_MENU_KEYBOARD)
            if user:
                log_activity(user.id, "voice")
        else:
            await processing_msg.edit_text("😔 Не удалось распознать голос.\n\nПопробуйте говорить чётче или напишите текстом!", reply_markup=MAIN_MENU_KEYBOARD)
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await processing_msg.edit_text("❌ Ошибка при обработке голоса.\n\nПожалуйста, напишите текстом.", reply_markup=MAIN_MENU_KEYBOARD)

async def handle_set_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_message = (update.message.text or "").strip()
    user = update.effective_user
    patterns = [r'я живу в ([а-яА-ЯёЁa-zA-Z\s\-]+)', r'я из ([а-яА-ЯёЁa-zA-Z\s\-]+)', r'мой город ([а-яА-ЯёЁa-zA-Z\s\-]+)', r'город ([а-яА-ЯёЁa-zA-Z\s\-]+)']
    city = None
    for pattern in patterns:
        match = re.search(pattern, user_message.lower())
        if match:
            city = match.group(1).strip().capitalize()
            break
    if city and len(city) > 1:
        context.user_data["city"] = city
        upsert_user(telegram_id=user.id if user else 0, role=context.user_data.get("role", "senior"), city=city)
        await update.message.reply_text(f"✅ Запомнила! Ваш город: **{city}**\n\n🌤️ Теперь узнаю погоду!", parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)

async def handle_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    reminders = list_reminders(user.id if user else 0)
    if not reminders:
        await update.message.reply_text("📋 У вас пока нет напоминаний.\n\n/add_meds — добавить", reply_markup=MAIN_MENU_KEYBOARD)
        return
    lines = ["📋 Ваши напоминания:"]
    for r in reminders:
        lines.append(f"{'✅' if r['enabled'] else '⏸'} {r['time_local']} — {r['text']}")
    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MENU_KEYBOARD)

async def handle_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(social_events_overview(), reply_markup=MAIN_MENU_KEYBOARD)

async def handle_sos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        log_activity(user.id, "sos")
    await update.message.reply_text("🆘 Сигнал SOS отправлен! Я уведомила ваших близких.", reply_markup=MAIN_MENU_KEYBOARD)
    if user:
        for rel_id in get_relatives_for_senior(user.id):
            try:
                await context.bot.send_message(chat_id=rel_id, text="🚨 ВНИМАНИЕ! Ваш близкий нажал SOS!")
            except Exception as e:
                logger.warning(f"Failed to notify {rel_id}: {e}")

async def handle_family(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    summary = get_activity_summary(user.id if user else 0)
    lines = ["👨‍👩‍👧 Статистика за 24 часа:"]
    lines.append(f"💬 Разговоров: {summary.get('talk', 0)}")
    lines.append(f"💊 Принято лекарств: {summary.get('reminder_done', 0)}")
    lines.append(f"🆘 Нажатий SOS: {summary.get('sos', 0)}")
    lines.append(f"🎤 Голосовых: {summary.get('voice', 0)}")
    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MENU_KEYBOARD)

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⚙️ Настройки\n\n/add_meds — напоминания\n/weather — погода\n/enable_checkin — ежедневный опрос\n/voice_help — голосовые", reply_markup=MAIN_MENU_KEYBOARD)

async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_talk(update, context)

# ==================== НАПОМИНАНИЯ ====================

async def add_meds_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("💊 Когда напоминать? Напишите время ЧЧ:ММ, например 09:00", reply_markup=ReplyKeyboardRemove())
    return MedsState.ASK_TIME.value

async def add_meds_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    parts = text.split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        await update.message.reply_text("Формат ЧЧ:ММ, например 08:30")
        return MedsState.ASK_TIME.value
    h, m = map(int, parts)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        await update.message.reply_text("Часы 00-23, минуты 00-59")
        return MedsState.ASK_TIME.value
    context.user_data["meds_time"] = f"{h:02d}:{m:02d}"
    await update.message.reply_text("Что напоминать? Например: «Принять таблетку»")
    return MedsState.ASK_TEXT.value

async def add_meds_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    meds_time = context.user_data.get("meds_time", "09:00")
    text = (update.message.text or "").strip() or "Принять лекарство"
    add_reminder(telegram_id=user.id if user else 0, kind="meds", text=text, time_local=meds_time)
    await update.message.reply_text(f"✅ Хорошо! Буду каждый день в {meds_time} напоминать: «{text}»", reply_markup=MAIN_MENU_KEYBOARD)
    return ConversationHandler.END

async def meds_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Отменено.", reply_markup=MAIN_MENU_KEYBOARD)
    return ConversationHandler.END

# ==================== ЕЖЕДНЕВНАЯ ПРОВЕРКА ====================

async def daily_checkin(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(chat_id=context.job.chat_id, text="🌞 Доброе утро! Как вы себя чувствуете?")

async def enable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    for job in context.job_queue.get_jobs_by_name(f"checkin-{chat_id}"):
        job.schedule_removal()
    context.job_queue.run_daily(daily_checkin, time=time(hour=10, minute=0), chat_id=chat_id, name=f"checkin-{chat_id}")
    await update.message.reply_text("✅ Включено! Буду спрашивать каждый день в 10:00.", reply_markup=MAIN_MENU_KEYBOARD)

async def disable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    for job in context.job_queue.get_jobs_by_name(f"checkin-{chat_id}"):
        job.schedule_removal()
    await update.message.reply_text("❌ Отключено.", reply_markup=MAIN_MENU_KEYBOARD)

# ==================== КОМАНДЫ ====================

async def voice_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🎤 Отправьте голосовое сообщение, я распознаю и отвечу!", reply_markup=MAIN_MENU_KEYBOARD)

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    city = context.user_data.get("city")
    if not city:
        await update.message.reply_text(f"{name}, скажите ваш город: «Я живу в Москве»", reply_markup=MAIN_MENU_KEYBOARD)
        return
    loading = await update.message.reply_text("🌤️ Узнаю погоду...")
    weather = await get_weather_async(city)
    await loading.delete()
    if weather:
        await update.message.reply_text(weather, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
    else:
        await update.message.reply_text(f"😔 Не найдено: {city}", reply_markup=MAIN_MENU_KEYBOARD)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🤖 **Команды:**\n/start — начать\n/weather — погода\n/add_meds — напоминания\n/enable_checkin — ежедневный опрос\n/voice_help — голосовые\n/menu — меню", parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📋 Главное меню:", reply_markup=MAIN_MENU_KEYBOARD)

async def companions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(social_companions_info(), reply_markup=MAIN_MENU_KEYBOARD)

async def volunteers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(social_volunteers_info(), reply_markup=MAIN_MENU_KEYBOARD)

async def health_extra_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(health_extra_info(), reply_markup=MAIN_MENU_KEYBOARD)

async def helper_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(home_helper_info(), reply_markup=MAIN_MENU_KEYBOARD)

async def games_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(games_menu_text(), reply_markup=MAIN_MENU_KEYBOARD)

async def nostalgia_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(nostalgia_menu_text(), reply_markup=MAIN_MENU_KEYBOARD)

async def courses_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(courses_menu_text(), reply_markup=MAIN_MENU_KEYBOARD)

async def achievements_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(achievements_text(), reply_markup=MAIN_MENU_KEYBOARD)

async def admin_analytics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(analytics_info_text(), reply_markup=MAIN_MENU_KEYBOARD)

async def add_relative_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /add_relative <ID>", reply_markup=MAIN_MENU_KEYBOARD)
        return
    try:
        senior_id = int(context.args[0])
        add_relative_link(senior_telegram_id=senior_id, relative_telegram_id=update.effective_user.id)
        await update.message.reply_text(f"✅ Готово! Связаны с {senior_id}.", reply_markup=MAIN_MENU_KEYBOARD)
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.", reply_markup=MAIN_MENU_KEYBOARD)

# ==================== ПОСТРОЕНИЕ ПРИЛОЖЕНИЯ ====================

def build_application():
    settings = get_settings()
    init_db()
    builder = ApplicationBuilder().token(settings.telegram_token)
    request = HTTPXRequest(connect_timeout=settings.telegram_connect_timeout, read_timeout=settings.telegram_read_timeout, write_timeout=settings.telegram_read_timeout, proxy=settings.telegram_proxy)
    builder = builder.request(request)
    application = builder.build()

    conv_handler = ConversationHandler(entry_points=[CommandHandler("start", start)], states={
        OnboardingState.CHOOSING_ROLE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_role)],
        OnboardingState.SENIOR_NAME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, senior_name)],
        OnboardingState.SENIOR_AGE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, senior_age)],
        OnboardingState.SENIOR_CITY.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, senior_city)],
        OnboardingState.SENIOR_INTERESTS.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, senior_interests)],
        OnboardingState.RELATIVE_CODE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, relative_code)],
    }, fallbacks=[])
    application.add_handler(conv_handler)

    meds_conv = ConversationHandler(entry_points=[CommandHandler("add_meds", add_meds_start)], states={
        MedsState.ASK_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_time)],
        MedsState.ASK_TEXT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_text)],
    }, fallbacks=[CommandHandler("cancel", meds_cancel)])
    application.add_handler(meds_conv)

    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("enable_checkin", enable_checkin))
    application.add_handler(CommandHandler("disable_checkin", disable_checkin))
    application.add_handler(CommandHandler("voice_help", voice_help))
    application.add_handler(CommandHandler("add_relative", add_relative_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("menu", menu_cmd))
    application.add_handler(CommandHandler("companions", companions_cmd))
    application.add_handler(CommandHandler("volunteers", volunteers_cmd))
    application.add_handler(CommandHandler("health_more", health_extra_cmd))
    application.add_handler(CommandHandler("helper", helper_cmd))
    application.add_handler(CommandHandler("games", games_cmd))
    application.add_handler(CommandHandler("nostalgia", nostalgia_cmd))
    application.add_handler(CommandHandler("courses", courses_cmd))
    application.add_handler(CommandHandler("achievements", achievements_cmd))
    application.add_handler(CommandHandler("admin_stats", admin_analytics_cmd))

    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.Regex(r'(живу в|город|я из)'), handle_set_city))
    application.add_handler(MessageHandler(filters.Regex("^(💬 Поговорить|📅 Напоминания|👥 События|🆘 ПОМОЩЬ|👨‍👩‍👧 Семья|⚙️ Настройки)$"), main_menu_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text))

    return application

# ==================== ЗАПУСК ====================

def main() -> None:
    settings = get_settings()
    logger.info("Starting bot...")
    if ai_service.available:
        logger.info(f"✅ AI Service ready")
    else:
        logger.warning("⚠️ AI Service disabled")
    if voice_processor.available:
        logger.info("✅ Voice processor ready")
    else:
        logger.warning("⚠️ Voice processor disabled")
    app = build_application()
    try:
        app.run_polling(close_loop=False, drop_pending_updates=True)
    except (TimedOut, NetworkError) as exc:
        print(f"\nError: {exc!r}\n", file=sys.stderr)
        raise SystemExit(1) from exc

if __name__ == "__main__":
    main()
