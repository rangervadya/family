from __future__ import annotations

import logging
import sys
from enum import Enum, auto
from typing import Final
from datetime import time

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


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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


MAIN_MENU_KEYBOARD: Final = ReplyKeyboardMarkup(
    [
        ["💬 Поговорить", "📅 Напоминания"],
        ["👥 События", "🆘 ПОМОЩЬ"],
        ["👨‍👩‍👧 Семья", "⚙️ Настройки"],
    ],
    resize_keyboard=True,
)


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

    # По умолчанию считаем, что это пожилой пользователь
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
    await update.message.reply_text(
        "Спасибо!\n\nВ каком городе вы живёте?",
    )
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

    upsert_user(
        telegram_id=telegram_id,
        role=role,
        name=name,
        age=age,
        city=city,
        interests=interests,
    )

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
    upsert_user(
        telegram_id=telegram_id,
        role=Role.RELATIVE.value,
        name=user.first_name if user else None,
        age=None,
        city=None,
        interests=None,
    )

    await update.message.reply_text(
        "Спасибо! На этом этапе мы считаем, что код принят.\n"
        "Позже здесь появится панель мониторинга для ваших близких.\n\n"
        "Пока что вы можете видеть тестовое меню:",
        reply_markup=MAIN_MENU_KEYBOARD,
    )
    return ConversationHandler.END


async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий главного меню (MVP-версия)."""
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
        # Fallback — перенаправляем в AI-диалог как "умный собеседник"
        await handle_talk(update, context)


async def handle_talk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Умный собеседник с вызовом AI-заглушки."""
    user = update.effective_user
    name = context.user_data.get("name") or (user.first_name if user else "друг")
    last_text = (update.message.text or "").strip()

    if user:
        log_activity(user.id, "talk")

    reply = await generate_companion_reply(last_text, name=name)
    await update.message.reply_text(reply)


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


async def handle_sos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user:
        log_activity(user.id, "sos")

    await update.message.reply_text(
        "Вы нажали SOS. Я зафиксировала это событие и, по возможности, уведомлю ваших близких.",
    )

    if user:
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
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to notify relative %s about SOS: %s", rel_id, e)


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
        "• /voice_help — рассказ о голосовом интерфейсе",
    )


async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка произвольного текста — считаем, что это разговор с компаньоном."""
    await handle_talk(update, context)


# ---------- Напоминания о лекарствах (простая настройка через команду) ----------


class MedsState(Enum):
    ASK_TIME = auto()
    ASK_TEXT = auto()


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
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💊 Напоминание: {text}",
        )
        log_activity(chat_id, "reminder_done")
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to send meds reminder to %s: %s", chat_id, e)


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

    # Зарегистрируем ежедневное напоминание в JobQueue (в рамках текущего запуска бота)
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
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to schedule meds reminder for %s at %s: %s", telegram_id, meds_time, e)

    await update.message.reply_text(
        f"Хорошо, я буду каждый день в {meds_time} напоминать вам: «{text}».\n\n"
        "Вы всегда можете посмотреть список напоминаний через кнопку «📅 Напоминания».",
        reply_markup=MAIN_MENU_KEYBOARD,
    )

    # TODO: регистрация задач в JobQueue — отдельный шаг (можно добавить позже)
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
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to send daily check-in to %s: %s", chat_id, e)


async def enable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Включить ежедневный вопрос «Как дела?» (простая версия: каждый день в 10:00)."""
    chat_id = update.effective_chat.id
    job_queue: JobQueue = context.job_queue

    # Удалим старые задания на всякий случай
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
        "Хорошо, я буду каждый день в 10:00 спрашивать, как у вас дела. 🌞",
    )


async def disable_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    job_queue: JobQueue = context.job_queue
    current_jobs = job_queue.get_jobs_by_name(f"checkin-{chat_id}")
    for job in current_jobs:
        job.schedule_removal()

    await update.message.reply_text(
        "Ежедневный вопрос «Как дела?» отключен.",
    )


async def voice_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(voice_interface_info())


# ---------- Привязка родственника (простая админ-команда) ----------


async def add_relative_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Простая команда /add_relative <id_пожилого>.

    Предполагаем, что команду вызывает родственник:
    /add_relative 123456789
    """
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

    add_relative_link(senior_telegram_id=senior_id, relative_telegram_id=user.id)
    await update.message.reply_text(
        f"Готово. Я связала вас с пользователем с Telegram ID {senior_id}.\n"
        "Теперь при нажатии SOS ему я постараюсь отправить вам уведомление.",
    )


# ---------- Дополнительные функции из ТЗ как отдельные команды ----------


async def companions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(social_companions_info())


async def volunteers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(social_volunteers_info())


async def health_extra_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(health_extra_info())


async def helper_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(home_helper_info())


async def games_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(games_menu_text())


async def nostalgia_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(nostalgia_menu_text())


async def courses_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(courses_menu_text())


async def achievements_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(achievements_text())


async def admin_analytics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(analytics_info_text())


# ---------- Навигация / help ----------


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Я бот-компаньон «Семья».\n\n"
        "Главные действия:\n"
        "• Кнопки внизу экрана — поговорить, напоминания, события, SOS, семья, настройки.\n"
        "• /menu — вернуть главное меню, если кнопки пропали.\n"
        "• /add_meds — добавить напоминание о лекарствах.\n"
        "• /weather — узнать погоду.\n"
        "• /enable_checkin — каждый день спрашивать «Как дела?».",
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Вот ваше главное меню.",
        reply_markup=MAIN_MENU_KEYBOARD,
    )


# ---------- Погода (простая команда) ----------


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


def build_application():
    settings = get_settings()
    init_db()

    builder = ApplicationBuilder().token(settings.telegram_token)
    # Прокси и таймауты — если без них ConnectTimeout до api.telegram.org
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

    # Настройка напоминаний о лекарствах
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

    # Погода
    application.add_handler(CommandHandler("weather", weather_command))

    # Ежедневная проверка «Как дела?»
    application.add_handler(CommandHandler("enable_checkin", enable_checkin))
    application.add_handler(CommandHandler("disable_checkin", disable_checkin))
    application.add_handler(CommandHandler("voice_help", voice_help))

    # Привязка родственника
    application.add_handler(CommandHandler("add_relative", add_relative_cmd))

    # Социальный активатор и прочие функции ТЗ
    application.add_handler(CommandHandler("companions", companions_cmd))
    application.add_handler(CommandHandler("volunteers", volunteers_cmd))
    application.add_handler(CommandHandler("health_more", health_extra_cmd))
    application.add_handler(CommandHandler("helper", helper_cmd))
    application.add_handler(CommandHandler("games", games_cmd))
    application.add_handler(CommandHandler("nostalgia", nostalgia_cmd))
    application.add_handler(CommandHandler("courses", courses_cmd))
    application.add_handler(CommandHandler("achievements", achievements_cmd))
    application.add_handler(CommandHandler("admin_stats", admin_analytics_cmd))

    # Навигация
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("menu", menu_cmd))

    # Главное меню (после онбординга)
    application.add_handler(
        MessageHandler(
            filters.Regex("^(💬 Поговорить|📅 Напоминания|👥 События|🆘 ПОМОЩЬ|👨‍👩‍👧 Семья|⚙️ Настройки)$"),
            main_menu_router,
        )
    )

    # Произвольный текст => разговор с компаньоном
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text)
    )

    return application


def main() -> None:
    settings = get_settings()
    logger.info("Starting bot with timezone %s", settings.default_timezone)
    if settings.telegram_proxy:
        # Не логируем логин/пароль в URL прокси
        safe = settings.telegram_proxy
        if "@" in safe and "://" in safe:
            scheme, rest = safe.split("://", 1)
            if "@" in rest:
                hostpart = rest.split("@", 1)[1]
                safe = f"{scheme}://***@{hostpart}"
        logger.info("Для Telegram используется прокси: %s", safe)
    else:
        logger.warning(
            "Прокси не задан (TELEGRAM_PROXY или HTTPS_PROXY). "
            "Если видите TimedOut — включите VPN и укажите локальный HTTP/SOCKS-прокси в .env."
        )

    app = build_application()
    try:
        # Убираем signal_handlers и используем обычный run_polling
        # Проблема с сигналами в потоке не критична для работы бота
        app.run_polling(
            close_loop=False, 
            drop_pending_updates=True
        )
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


def get_application():
    return build_application()
