from __future__ import annotations

import os
import logging
import sys
import json
import sqlite3
from enum import Enum, auto
from typing import Final, Optional, Dict, List, Any
from datetime import time, datetime, timedelta
from io import BytesIO

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

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ==================== AI СЕРВИС ====================

class AIService:
    """Сервис для работы с AI через OpenRouter"""
    
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.model = os.environ.get("AI_MODEL", "google/gemini-2.0-flash-exp:free")
        self.available = bool(self.api_key)
        
        if self.available:
            logger.info(f"✅ AI Service initialized with model: {self.model}")
        else:
            logger.warning("⚠️ AI Service disabled: OPENROUTER_API_KEY not set")
    
    async def generate_response(
        self, 
        message: str, 
        user_id: int,
        user_name: str = "Пользователь"
    ) -> str:
        """Генерация ответа через AI"""
        
        if not self.available:
            return self._fallback_response(message, user_name)
        
        # Получаем контекст из памяти
        memory = await self.get_user_memory(user_id)
        
        # Формируем системный промпт
        system_prompt = self._get_system_prompt(user_name, memory)
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": message}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 500
                    }
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data["choices"][0]["message"]["content"]
                    else:
                        logger.error(f"AI API error: {response.status}")
                        return self._fallback_response(message, user_name)
        except Exception as e:
            logger.error(f"AI request failed: {e}")
            return self._fallback_response(message, user_name)
    
    def _get_system_prompt(self, user_name: str, memory: str = "") -> str:
        prompt = f"""Ты — заботливый бот-компаньон «Семья». Ты общаешься с {user_name}.

Правила общения:
1. Отвечай тепло, дружелюбно и заботливо
2. Используй простые, понятные предложения
3. Если нужно напомнить о здоровье — напомни
4. Интересуйся самочувствием пользователя
5. Не используй сложные технические термины
6. Будь терпеливым и понимающим

Твоя цель — поддерживать приятную беседу и помогать пользователю."""
        
        if memory:
            prompt += f"\n\nИнформация о пользователе из памяти:\n{memory}"
        
        return prompt
    
    def _fallback_response(self, message: str, user_name: str) -> str:
        """Ответ-заглушка при недоступности AI"""
        message_lower = message.lower()
        
        if any(word in message_lower for word in ['привет', 'здравствуй']):
            return f"Здравствуйте, {user_name}! 🌷 Рада вас видеть!"
        
        if any(word in message_lower for word in ['как дела', 'как ты']):
            return f"У меня всё отлично, {user_name}! А как вы себя чувствуете?"
        
        if any(word in message_lower for word in ['спасибо', 'благодарю']):
            return f"Пожалуйста, {user_name}! 😊 Всегда рада помочь."
        
        return (
            f"Спасибо за ваше сообщение, {user_name}! 😊\n\n"
            f"Если вам нужна помощь с напоминаниями, прогнозом погоды "
            f"или просто хочется поговорить — я всегда здесь!"
        )
    
    async def get_user_memory(self, user_id: int) -> str:
        """Получение сохранённой информации о пользователе"""
        try:
            conn = sqlite3.connect('family_bot.db')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, age, city, interests FROM users WHERE telegram_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            conn.close()
            
            if row and any(row):
                facts = []
                if row[0]: facts.append(f"Имя: {row[0]}")
                if row[1]: facts.append(f"Возраст: {row[1]}")
                if row[2]: facts.append(f"Город: {row[2]}")
                if row[3]: facts.append(f"Интересы: {row[3]}")
                return "\n".join(facts)
        except Exception as e:
            logger.error(f"Memory error: {e}")
        return ""

# Глобальный экземпляр AI сервиса
ai_service = AIService()

# ==================== ОСТАЛЬНЫЕ ИМПОРТЫ ====================

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

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

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
    """Умный собеседник с AI"""
    user = update.effective_user
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    user_message = (update.message.text or "").strip()
    
    # Убираем эмодзи, если они есть в начале
    if user_message and user_message[0] in ["💬", "📅", "👥", "🆘", "👨‍👩‍👧", "⚙️"]:
        user_message = user_message[1:].strip()
        if not user_message:
            await update.message.reply_text(
                "Выберите, пожалуйста, действие из меню или просто напишите мне что-нибудь! 😊",
                reply_markup=MAIN_MENU_KEYBOARD,
            )
            return

    if user:
        log_activity(user.id, "talk")

    # Отправляем уведомление о начале генерации
    thinking_msg = await update.message.reply_text("🤔 Думаю над ответом...")

    # Генерируем ответ через AI
    reply = await ai_service.generate_response(
        message=user_message,
        user_id=user.id if user else 0,
        user_name=name
    )

    await thinking_msg.delete()
    await update.message.reply_text(reply, reply_markup=MAIN_MENU_KEYBOARD)

async def handle_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    telegram_id = user.id if user else 0
    reminders = list_reminders(telegram_id)

    if not reminders:
        await update.message.reply_text(
            "У вас пока нет напоминаний.\n\n"
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
    await update.message.reply_text(
        social_events_overview(),
        reply_markup=MAIN_MENU_KEYBOARD,
    )

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
                    text=(
                        "🚨 ВНИМАНИЕ! 🚨\n\n"
                        f"Ваш близкий (Telegram ID {user.id}) нажал кнопку SOS.\n"
                        "Пожалуйста, свяжитесь с ним как можно скорее!"
                    ),
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

# ==================== ГОЛОСОВЫЕ СООБЩЕНИЯ ====================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка голосовых сообщений"""
    user = update.effective_user
    voice: Voice = update.message.voice
    
    if not voice:
        return

    await update.message.reply_text(
        "🎤 Получил ваше голосовое сообщение!\n\n"
        "К сожалению, распознавание голоса пока в разработке. "
        "Пожалуйста, напишите текстом или используйте кнопки меню. 😊",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

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
        voice_interface_info(),
        reply_markup=MAIN_MENU_KEYBOARD,
    )

async def add_relative_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not context.args:
        await update.message.reply_text(
            "👨‍👩‍👧 Использование: /add_relative <Telegram ID пожилого пользователя>\n"
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
        f"✅ Готово! Вы связаны с пользователем {senior_id}.\n"
        "Теперь вы будете получать уведомления при нажатии SOS.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    city = context.user_data.get("city")

    if not city:
        await update.message.reply_text(
            f"{name}, я пока не знаю ваш город.\n"
            "Напишите мне: «Я живу в <город>», и я запомню.",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return

    thinking = await update.message.reply_text("🌤️ Узнаю погоду...")
    summary = await get_weather_summary(city)
    await thinking.delete()

    if not summary:
        await update.message.reply_text(
            "❌ Не получилось получить прогноз. Попробуйте позже.",
            reply_markup=MAIN_MENU_KEYBOARD,
        )
        return

    await update.message.reply_text(
        f"🌤️ Доброе утро, {name}!\n\n{summary}",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

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

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 **Бот-компаньон «Семья»**\n\n"
        "**Основные команды:**\n"
        "• /start — начать общение\n"
        "• /menu — показать главное меню\n"
        "• /help — эта справка\n\n"
        "**Здоровье:**\n"
        "• /add_meds — добавить напоминание о лекарствах\n"
        "• /weather — прогноз погоды\n"
        "• /enable_checkin — ежедневный опрос\n\n"
        "**Общение:**\n"
        "• /companions — поиск компаньонов\n"
        "• /volunteers — волонтёрская помощь\n"
        "• /games — игры\n"
        "• /nostalgia — ностальгия\n"
        "• /courses — курсы\n\n"
        "**Семья:**\n"
        "• /add_relative — привязать родственника\n"
        "• /voice_help — голосовые сообщения\n\n"
        "**Статистика:**\n"
        "• /admin_stats — аналитика (для админов)",
        reply_markup=MAIN_MENU_KEYBOARD,
        parse_mode="Markdown",
    )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📋 Вот ваше главное меню:",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

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

    # Выводим статус AI
    if ai_service.available:
        logger.info("✅ AI Service is ready")
    else:
        logger.warning("⚠️ AI Service disabled (add OPENROUTER_API_KEY to enable)")

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

def get_application():
    return build_application()
