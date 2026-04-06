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
    """Получение погоды через OpenWeatherMap"""
    
    api_key = os.environ.get("OPENWEATHER_API_KEY", "")
    if not api_key:
        return None
    
    city_normalized = city.strip().lower()
    city_normalized = city_normalized.replace("ё", "е")
    
    city_map = {
        "москва": "Moscow",
        "санкт-петербург": "Saint Petersburg",
        "новосибирск": "Novosibirsk",
        "екатеринбург": "Yekaterinburg",
        "казань": "Kazan",
        "нижний новгород": "Nizhny Novgorod",
        "краснодар": "Krasnodar",
        "сочи": "Sochi",
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
                        
                        weather_emoji = {
                            "ясно": "☀️", "солнечно": "☀️",
                            "облачно": "☁️", "пасмурно": "☁️",
                            "дождь": "🌧️", "ливень": "🌧️",
                            "снег": "❄️", "метель": "❄️",
                            "гроза": "⛈️", "туман": "🌫️", "ветер": "💨"
                        }
                        
                        emoji = "🌡️"
                        for key, val in weather_emoji.items():
                            if key in description.lower():
                                emoji = val
                                break
                        
                        return (
                            f"{emoji} **Погода в {city_name}**\n\n"
                            f"🌡️ Температура: **{temp}°C**\n"
                            f"🤔 Ощущается как: **{feels_like}°C**\n"
                            f"💧 Влажность: **{humidity}%**\n"
                            f"💨 Ветер: **{wind_speed} м/с**\n"
                            f"📖 Описание: **{description.capitalize()}**"
                        )
                    elif response.status == 404:
                        continue
        except Exception as e:
            logger.error(f"Weather error for {try_city}: {e}")
            continue
    
    return None

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
            "Пожалуйста, введите код привязки.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return OnboardingState.RELATIVE_CODE.value

    context.user_data["role"] = Role.SENIOR.value
    await update.message.reply_text(
        "Рада знакомству! 🌷 Как вас зовут?",
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
        await update.message.reply_text("Пожалуйста, введите число.")
        return OnboardingState.SENIOR_AGE.value

    context.user_data["age"] = int(text)
    await update.message.reply_text("В каком городе вы живёте?")
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
    
    upsert_user(
        telegram_id=telegram_id,
        role=context.user_data.get("role", Role.SENIOR.value),
        name=context.user_data.get("name"),
        age=context.user_data.get("age"),
        city=context.user_data.get("city"),
        interests=context.user_data.get("interests"),
    )

    name_for_text = context.user_data.get("name") or "друг"
    await update.message.reply_text(
        f"Спасибо, {name_for_text}! Я всё запомнила.\n\n"
        "Теперь вы можете пользоваться мной как компаньоном.\n\n"
        "Вот главное меню:",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    return ConversationHandler.END

async def relative_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    telegram_id = user.id if user else 0
    upsert_user(
        telegram_id=telegram_id,
        role=Role.RELATIVE.value,
        name=user.first_name if user else None,
    )

    await update.message.reply_text(
        "Спасибо! Код принят.\n\n"
        "Вот главное меню:",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
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
    """Умный собеседник с AI и обработкой команд"""
    user = update.effective_user
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    user_message = (update.message.text or "").strip()
    
    if user_message and user_message[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️"]:
        user_message = user_message[1:].strip()
        if not user_message:
            await update.message.reply_text(
                "Напишите мне что-нибудь, и мы поговорим! 😊",
                reply_markup=MAIN_MENU_KEYBOARD,
            )
            return

    if user:
        log_activity(user.id, "talk")
    
    user_message_lower = user_message.lower()
    
    # Погода
    if any(word in user_message_lower for word in ['погод', 'прогноз', 'солнце', 'дождь', 'ветер', 'температура', 'градус']):
        city = context.user_data.get("city")
        
        words = user_message.split()
        for word in words:
            if word not in ['погода', 'какая', 'прогноз', 'покажи', 'узнай']:
                if len(word) > 2:
                    city = word
                    break
        
        if not city:
            await update.message.reply_text(
                "🌤️ Чтобы узнать погоду, скажите мне ваш город.\n\n"
                "Например: «Я живу в Москве» или «Погода в Санкт-Петербурге»",
                reply_markup=MAIN_MENU_KEYBOARD,
            )
            return
        
        loading_msg = await update.message.reply_text("🌤️ Узнаю погоду...")
        weather_info = await get_weather_async(city)
        await loading_msg.delete()
        
        if weather_info:
            await update.message.reply_text(weather_info, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
        else:
            await update.message.reply_text(
                f"😔 Не удалось найти погоду для города «{city}».\n\n"
                f"Проверьте название и попробуйте ещё раз.",
                reply_markup=MAIN_MENU_KEYBOARD,
            )
        return
    
    # Время и дата
    if any(word in user_message_lower for word in ['время', 'часы', 'который час', 'дата', 'сегодня', 'какой день', 'число']):
        now = datetime.now()
        await update.message.reply_text(
            f"📅 Сегодня {now.strftime('%d.%m.%Y')}\n"
            f"🕐 Сейчас {now.strftime('%H:%M')}",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return
    
    # Приветствие
    if any(word in user_message_lower for word in ['привет', 'здравствуй', 'доброе утро', 'добрый день', 'добрый вечер', 'здрасьте', 'здравствуйте']):
        greeting = (
            f"Здравствуйте, {name}! 🌷\n\n"
            f"Чем могу помочь сегодня?\n\n"
            f"• 🌤️ Спросите «какая погода»\n"
            f"• 💊 Напишите /add_meds для напоминаний\n"
            f"• 🎤 Отправьте голосовое сообщение\n"
            f"• 💬 Просто поболтаем — напишите что-нибудь"
        )
        await update.message.reply_text(greeting, reply_markup=MAIN_MENU_KEYBOARD)
        return
    
    # Как дела
    if any(word in user_message_lower for word in ['как дела', 'как ты', 'дела как', 'как поживаешь', 'как настроение', 'как жизнь']):
        response = (
            f"У меня всё отлично, {name}! 😊\n\n"
            f"Я каждый день учусь новому, чтобы лучше вам помогать.\n"
            f"А как вы себя чувствуете сегодня?"
        )
        await update.message.reply_text(response, reply_markup=MAIN_MENU_KEYBOARD)
        return
    
    # Помощь
    if any(word in user_message_lower for word in ['помощь', 'help', 'что умеешь', 'команды', 'функции', 'возможности', 'список команд']):
        help_text = (
            f"🤖 **Что я умею, {name}:**\n\n"
            f"• 🌤️ **Погода** — спросите «какая погода»\n"
            f"• 🎤 **Голосовые сообщения** — отправьте голосовое\n"
            f"• 💊 **Напоминания** — команда /add_meds\n"
            f"• 💬 **Поговорить** — напишите что угодно\n"
            f"• 👨‍👩‍👧 **Семья** — кнопка в меню\n"
            f"• 🆘 **SOS** — экстренная помощь\n"
            f"• 🕐 **Время** — спросите «который час»\n\n"
            f"Я здесь, чтобы поддержать вас! 🌷"
        )
        await update.message.reply_text(help_text, reply_markup=MAIN_MENU_KEYBOARD, parse_mode="Markdown")
        return
    
    # Спасибо
    if any(word in user_message_lower for word in ['спасибо', 'благодарю', 'пасиб']):
        await update.message.reply_text(
            f"Пожалуйста, {name}! 😊 Всегда рада помочь!",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return

    # AI ответ
    thinking_msg = await update.message.reply_text("🤔 Думаю над ответом...")

    try:
        reply = await ai_service.generate_response(
            message=user_message,
            user_id=user.id if user else 0,
            user_name=name
        )
        await thinking_msg.delete()
        await update.message.reply_text(reply, reply_markup=MAIN_MENU_KEYBOARD)
    except Exception as e:
        await thinking_msg.delete()
        logger.error(f"AI error: {e}")
        await update.message.reply_text(
            f"Извините, {name}, у меня небольшие технические трудности. Попробуйте ещё раз! 😊",
            reply_markup=MAIN_MENU_KEYBOARD,
        )

# ==================== ГОЛОСОВЫЕ СООБЩЕНИЯ ====================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка голосовых сообщений"""
    user = update.effective_user
    voice = update.message.voice
    
    if not voice:
        return
    
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    
    # Отправляем сообщение о начале обработки
    processing_msg = await update.message.reply_text(
        "🎤 Слушаю ваше голосовое сообщение...\n\nЭто может занять несколько секунд."
    )
    
    try:
        logger.info(f"🎤 Processing voice message from user {user.id if user else 'unknown'}")
        logger.info(f"🎤 Voice duration: {voice.duration} seconds")
        
        # Скачиваем голосовое сообщение
        file = await context.bot.get_file(voice.file_id)
        logger.info(f"🎤 File downloaded: {file.file_id}")
        
        audio_bytes = await file.download_as_bytearray()
        logger.info(f"🎤 Audio bytes size: {len(audio_bytes)} bytes")
        
        # Распознаём текст
        logger.info("🎤 Calling voice_processor.process_voice()...")
        recognized_text = await voice_processor.process_voice(bytes(audio_bytes))
        logger.info(f"🎤 Recognized text: '{recognized_text}'")
        
        if recognized_text:
            await processing_msg.edit_text(
                f"📝 Я распознал(а):\n\n*\"{recognized_text}\"*\n\n🤔 Думаю над ответом...",
                parse_mode="Markdown"
            )
            
            # Генерируем ответ через AI
            reply = await ai_service.generate_response(
                message=recognized_text,
                user_id=user.id if user else 0,
                user_name=name
            )
            
            await processing_msg.delete()
            await update.message.reply_text(reply, reply_markup=MAIN_MENU_KEYBOARD)
            
            if user:
                log_activity(user.id, "voice")
        else:
            await processing_msg.edit_text(
                "😔 Не удалось распознать голосовое сообщение.\n\n"
                "Попробуйте:\n"
                "• Говорить чётче и медленнее\n"
                "• Отправить сообщение короче (5-10 секунд)\n"
                "• Или просто напишите текстом",
                reply_markup=MAIN_MENU_KEYBOARD,
            )
            
    except Exception as e:
        logger.error(f"Voice handling error: {e}", exc_info=True)
        await processing_msg.edit_text(
            f"❌ Произошла ошибка: {str(e)[:100]}\n\nПопробуйте ещё раз или напишите текстом.",
            reply_markup=MAIN_MENU_KEYBOARD,
        )

async def handle_set_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка сообщений о городе"""
    user_message = (update.message.text or "").strip()
    user = update.effective_user
    
    patterns = [
        r'я живу в ([а-яА-ЯёЁa-zA-Z\s\-]+)',
        r'я из ([а-яА-ЯёЁa-zA-Z\s\-]+)',
        r'мой город ([а-яА-ЯёЁa-zA-Z\s\-]+)',
        r'город ([а-яА-ЯёЁa-zA-Z\s\-]+)',
        r'живу в ([а-яА-ЯёЁa-zA-Z\s\-]+)',
        r'погода в ([а-яА-ЯёЁa-zA-Z\s\-]+)',
    ]
    
    city = None
    
    for pattern in patterns:
        match = re.search(pattern, user_message.lower())
        if match:
            city = match.group(1).strip()
            city = city[0].upper() + city[1:] if city else None
            break
    
    if city and len(city) > 1:
        context.user_data["city"] = city
        upsert_user(
            telegram_id=user.id if user else 0,
            role=context.user_data.get("role", "senior"),
            name=context.user_data.get("name"),
            age=context.user_data.get("age"),
            city=city,
            interests=context.user_data.get("interests"),
        )
        await update.message.reply_text(
            f"✅ Запомнила! Ваш город: **{city}**\n\n"
            f"🌤️ Теперь вы можете узнать погоду!",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU_KEYBOARD,
        )

async def handle_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    telegram_id = user.id if user else 0
    reminders = list_reminders(telegram_id)

    if not reminders:
        await update.message.reply_text(
            "📋 У вас пока нет напоминаний.\n\n"
            "Отправьте команду /add_meds, чтобы добавить напоминание о лекарствах.",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return

    lines = ["📋 Ваши напоминания:"]
    for r in reminders:
        status = "✅" if r["enabled"] else "⏸"
        lines.append(f"{status} {r['time_local']} — {r['text']}")

    lines.append("\n/add_meds — добавить новое напоминание")
    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MENU_KEYBOARD)

async def handle_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(social_events_overview(), reply_markup=MAIN_MENU_KEYBOARD)

async def handle_sos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        log_activity(user.id, "sos")

    await update.message.reply_text(
        "🆘 Сигнал SOS отправлен! Я уведомила ваших близких.\n\n"
        "Если вам нужна срочная помощь — пожалуйста, свяжитесь с экстренными службами по номеру 112.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

    if user:
        relatives = get_relatives_for_senior(user.id)
        for rel_id in relatives:
            try:
                await context.bot.send_message(
                    chat_id=rel_id,
                    text="🚨 ВНИМАНИЕ! 🚨\n\nВаш близкий человек нажал кнопку SOS.\nПожалуйста, свяжитесь с ним как можно скорее!",
                )
            except Exception as e:
                logger.warning(f"Failed to notify relative {rel_id}: {e}")

async def handle_family(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    telegram_id = user.id if user else 0
    summary = get_activity_summary(telegram_id)

    lines = ["👨‍👩‍👧 Семейная статистика за 24 часа:"]
    lines.append(f"💬 Разговоров: {summary.get('talk', 0)}")
    lines.append(f"💊 Принято лекарств: {summary.get('reminder_done', 0)}")
    lines.append(f"🆘 Нажатий SOS: {summary.get('sos', 0)}")
    lines.append(f"🎤 Голосовых сообщений: {summary.get('voice', 0)}")

    await update.message.reply_text("\n".join(lines), reply_markup=MAIN_MENU_KEYBOARD)

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "⚙️ Настройки\n\n"
        "Доступные команды:\n"
        "• /add_meds — добавить напоминание о лекарствах\n"
        "• /weather — узнать погоду\n"
        "• /enable_checkin — включить ежедневный опрос\n"
        "• /disable_checkin — выключить ежедневный опрос\n"
        "• /voice_help — помощь по голосовым сообщениям\n"
        "• /help — все команды",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_talk(update, context)

# ==================== НАПОМИНАНИЯ О ЛЕКАРСТВАХ ====================

async def add_meds_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "💊 Когда напоминать о приёме лекарств?\n"
        "Напишите время в формате ЧЧ:ММ, например 09:00",
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
        await update.message.reply_text("Часы от 00 до 23, минуты от 00 до 59.")
        return MedsState.ASK_TIME.value

    context.user_data["meds_time"] = f"{h:02d}:{m:02d}"
    await update.message.reply_text(
        "Что мне напоминать?\n"
        "Например: «Принять таблетку от давления»",
    )
    return MedsState.ASK_TEXT.value

async def add_meds_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    telegram_id = user.id if user else 0

    meds_time = context.user_data.get("meds_time", "09:00")
    text = (update.message.text or "").strip() or "Принять лекарство"

    add_reminder(
        telegram_id=telegram_id,
        kind="meds",
        text=text,
        time_local=meds_time,
    )

    await update.message.reply_text(
        f"✅ Хорошо! Я буду каждый день в {meds_time} напоминать: «{text}»\n\n"
        "Вы всегда можете посмотреть список напоминаний через кнопку «📅 Напоминания».",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    return ConversationHandler.END

async def meds_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ Настройка напоминания отменена.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    return ConversationHandler.END

# ==================== ЕЖЕДНЕВНАЯ ПРОВЕРКА ====================

async def daily_checkin(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    chat_id = job.chat_id
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🌞 Доброе утро! Как вы себя сегодня чувствуете?\n\n"
                 "Расскажите мне, как прошла ночь, и я подберу для вас хорошее начало дня!",
        )
    except Exception as e:
        logger.warning(f"Failed to send daily check-in to {chat_id}: {e}")

async def enable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    job_queue: JobQueue = context.job_queue

    current_jobs = job_queue.get_jobs_by_name(f"checkin-{chat_id}")
    for job in current_jobs:
        job.schedule_removal()

    job_queue.run_daily(
        daily_checkin,
        time=time(hour=10, minute=0),
        chat_id=chat_id,
        name=f"checkin-{chat_id}",
    )

    await update.message.reply_text(
        "✅ Включено! Я буду каждый день в 10:00 спрашивать, как у вас дела. 🌞",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

async def disable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    job_queue: JobQueue = context.job_queue
    current_jobs = job_queue.get_jobs_by_name(f"checkin-{chat_id}")
    for job in current_jobs:
        job.schedule_removal()

    await update.message.reply_text(
        "❌ Ежедневный вопрос отключён.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

# ==================== ВСПОМОГАТЕЛЬНЫЕ КОМАНДЫ ====================

async def voice_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎤 **Голосовой помощник**\n\n"
        "Вы можете отправлять мне голосовые сообщения!\n\n"
        "• Нажмите на значок микрофона 🎤 в Telegram\n"
        "• Скажите, что хотите (например, «Какая погода?»)\n"
        "• Отправьте сообщение\n"
        "• Я распознаю речь и отвечу\n\n"
        "Голосовые сообщения обрабатываются через нейросеть, "
        "поэтому они могут быть неидеальны. Говорите чётко и не слишком быстро!",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

async def add_relative_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not context.args:
        await update.message.reply_text(
            "👨‍👩‍👧 Использование: /add_relative <Telegram ID>\n"
            "Пример: /add_relative 123456789",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return

    try:
        senior_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом.")
        return

    if not user:
        await update.message.reply_text("❌ Не удалось определить ваш ID.")
        return

    add_relative_link(senior_telegram_id=senior_id, relative_telegram_id=user.id)
    await update.message.reply_text(
        f"✅ Готово! Вы связаны с пользователем {senior_id}.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    
    city = context.user_data.get("city")
    
    if update.message.text:
        text = update.message.text.replace("/weather", "").strip()
        if text:
            city = text
    
    if not city:
        await update.message.reply_text(
            f"{name}, я не знаю ваш город.\n\n"
            f"🌆 Напишите «Я живу в Москве» или используйте команду:\n"
            f"`/weather Москва`",
            parse_mode="Markdown",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return
    
    loading_msg = await update.message.reply_text("🌤️ Узнаю погоду...")
    weather_info = await get_weather_async(city)
    await loading_msg.delete()
    
    if weather_info:
        await update.message.reply_text(weather_info, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)
    else:
        await update.message.reply_text(
            f"😔 {name}, не удалось найти погоду для города «{city}».",
            reply_markup=MAIN_MENU_KEYBOARD,
        )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 **Бот-компаньон «Семья»**\n\n"
        "**Основные команды:**\n"
        "• /start — начать общение\n"
        "• /menu — показать главное меню\n"
        "• /help — эта справка\n\n"
        "**Погода:**\n"
        "• /weather — прогноз погоды\n"
        "• «Какая погода?» — спросите в чате\n\n"
        "**Голос:**\n"
        "• 🎤 Отправьте голосовое сообщение\n"
        "• /voice_help — помощь по голосовым сообщениям\n\n"
        "**Здоровье:**\n"
        "• /add_meds — добавить напоминание о лекарствах\n"
        "• /enable_checkin — ежедневный опрос\n\n"
        "**Семья:**\n"
        "• /add_relative — привязать родственника\n\n"
        "**Другое:**\n"
        "• «Который час?» — текущее время\n"
        "• «Привет» — начать диалог",
        reply_markup=MAIN_MENU_KEYBOARD,
        parse_mode="Markdown",
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("📋 Вот ваше главное меню:", reply_markup=MAIN_MENU_KEYBOARD)

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

# ==================== ПОСТРОЕНИЕ ПРИЛОЖЕНИЯ ====================

def build_application():
    settings = get_settings()
    init_db()

    builder = ApplicationBuilder().token(settings.telegram_token)
    
    request = HTTPXRequest(
        connect_timeout=settings.telegram_connect_timeout,
        read_timeout=settings.telegram_read_timeout,
        write_timeout=settings.telegram_read_timeout,
        proxy=settings.telegram_proxy,
    )
    builder = builder.request(request)

    application = builder.build()

    # Онбординг
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            OnboardingState.CHOOSING_ROLE.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_role)
            ],
            OnboardingState.SENIOR_NAME.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, senior_name)
            ],
            OnboardingState.SENIOR_AGE.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, senior_age)
            ],
            OnboardingState.SENIOR_CITY.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, senior_city)
            ],
            OnboardingState.SENIOR_INTERESTS.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, senior_interests)
            ],
            OnboardingState.RELATIVE_CODE.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, relative_code)
            ],
        },
        fallbacks=[],
    )
    application.add_handler(conv_handler)

    # Напоминания о лекарствах
    meds_conv = ConversationHandler(
        entry_points=[CommandHandler("add_meds", add_meds_start)],
        states={
            MedsState.ASK_TIME.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_time)
            ],
            MedsState.ASK_TEXT.value: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_text)
            ],
        },
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(meds_conv)

    # Основные команды
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("enable_checkin", enable_checkin))
    application.add_handler(CommandHandler("disable_checkin", disable_checkin))
    application.add_handler(CommandHandler("voice_help", voice_help))
    application.add_handler(CommandHandler("add_relative", add_relative_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("menu", menu_cmd))

    # Дополнительные функции
    application.add_handler(CommandHandler("companions", companions_cmd))
    application.add_handler(CommandHandler("volunteers", volunteers_cmd))
    application.add_handler(CommandHandler("health_more", health_extra_cmd))
    application.add_handler(CommandHandler("helper", helper_cmd))
    application.add_handler(CommandHandler("games", games_cmd))
    application.add_handler(CommandHandler("nostalgia", nostalgia_cmd))
    application.add_handler(CommandHandler("courses", courses_cmd))
    application.add_handler(CommandHandler("achievements", achievements_cmd))
    application.add_handler(CommandHandler("admin_stats", admin_analytics_cmd))

    # Голосовые сообщения
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Определение города
    application.add_handler(
        MessageHandler(
            filters.Regex(r'(живу в|город|в городе|я из|проживаю в|город мой|погода в)'), 
            handle_set_city
        )
    )

    # Главное меню
    application.add_handler(
        MessageHandler(
            filters.Regex("^(💬 Поговорить|📅 Напоминания|👥 События|🆘 ПОМОЩЬ|👨‍👩‍👧 Семья|⚙️ Настройки)$"),
            main_menu_router,
        )
    )

    # Произвольный текст
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text)
    )

    return application

# ==================== ЗАПУСК ====================

def main() -> None:
    settings = get_settings()
    logger.info("Starting bot with timezone %s", settings.default_timezone)
    
    if settings.telegram_proxy:
        safe = settings.telegram_proxy
        if "@" in safe and "://" in safe:
            scheme, rest = safe.split("://", 1)
            if "@" in rest:
                hostpart = rest.split("@", 1)[1]
                safe = f"{scheme}://***@{hostpart}"
        logger.info("Using proxy: %s", safe)
    else:
        logger.warning("No proxy configured")

    if ai_service.available:
        logger.info(f"✅ AI Service ready with model: {ai_service.model}")
    else:
        logger.warning("⚠️ AI Service disabled (add OPENROUTER_API_KEY)")

    if voice_processor.available:
        logger.info("✅ Voice processor ready (OpenRouter Whisper)")
    else:
        logger.warning("⚠️ Voice processor disabled (add OPENROUTER_API_KEY)")

    app = build_application()
    try:
        app.run_polling(close_loop=False, drop_pending_updates=True)
    except (TimedOut, NetworkError) as exc:
        print(
            "\n──────── Cannot connect to Telegram API ────────\n"
            f"Error: {exc!r}\n"
            "─────────────────────────────────────────────────\n",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

if __name__ == "__main__":
    main()
