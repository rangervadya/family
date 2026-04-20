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
    init_media_table,
    save_media,
    get_family_media,
    get_birthdays_for_date,
    get_user_language,
    set_user_language,
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


# ==================== МНОГОЯЗЫЧНОСТЬ ====================
TEXTS: Dict[str, Dict[str, str]] = {
    'ru': {
        'start': "Здравствуйте! Я бот-компаньон «Семья» 🏡\n\nДавайте познакомимся.\nКто вы?\n\n➤ Я пожилой пользователь\n➤ Я родственник/опекун",
        'choose_role': "Хорошо! Вы родственник.\nПожалуйста, введите код привязки, который мы выдадим вашему близкому человеку.",
        'senior_name': "Рада знакомству! 🌷 Как вас зовут?\n\nНапишите, пожалуйста, как к вам обращаться.",
        'senior_age': "Очень приятно, {name}!\n\nПодскажите, пожалуйста, сколько вам лет?",
        'senior_city': "Спасибо!\n\nВ каком городе вы живёте?",
        'senior_interests': "Отлично!\n\nРасскажите, чем вы любите заниматься? Например: сад, книги, фильмы, вязание, шахматы…",
        'senior_complete': "Спасибо, {name}! Я всё запомнила.\n\nТеперь вы можете пользоваться мной как компаньоном.\n\nВот главное меню:",
        'relative_complete': "Спасибо! Код принят.\n\nВот главное меню:",
        'lang_changed': "✅ Язык изменён на русский",
        'lang_usage': "📝 Использование: /lang ru или /lang en",
        'lang_invalid': "❌ Поддерживаются языки: ru, en",
        'menu': "📋 Главное меню:",
        'talk_placeholder': "Напишите что-нибудь! 😊",
        'no_reminders': "📋 У вас пока нет напоминаний.\n\nЯ могу каждый день напоминать о лекарствах.\nОтправьте команду /add_meds, чтобы добавить напоминание.",
        'reminders_list': "📋 Ваши напоминания:",
        'add_reminder_prompt': "Когда напоминать о приёме лекарств?\nНапишите время в формате ЧЧ:ММ, например 09:00 или 21:30.",
        'add_reminder_time_invalid': "Пожалуйста, введите время в формате ЧЧ:ММ, например 08:30.",
        'add_reminder_text_prompt': "Что мне напоминать?\nНапример: «Принять таблетку от давления».",
        'add_reminder_success': "Хорошо, я буду каждый день в {time} напоминать вам: «{text}».\n\nВы всегда можете посмотреть список напоминаний через кнопку «📅 Напоминания».",
        'add_reminder_cancel': "Настройка напоминания отменена.",
        'sos_sent': "Вы нажали SOS. Я зафиксировала это событие и, по возможности, уведомлю ваших близких.",
        'sos_notification': "Внимание.\n\nВаш близкий (Telegram ID {id}) нажал кнопку SOS в боте «Семья».\nПожалуйста, свяжитесь с ним как можно скорее.",
        'sos_feed': "Нажата кнопка SOS!",
        'sos_notify_family': "🚨 *{name}* нажал(а) SOS! Пожалуйста, проверьте семейную ленту.",
        'family_feed_empty': "📭 В семейной ленте пока нет сообщений.",
        'family_feed_title': "📋 *Семейная лента:*\n",
        'family_send_usage': "📝 Использование: /family_send <текст сообщения>",
        'family_send_success': "✅ Сообщение отправлено в семейную ленту!",
        'family_send_notify': "📢 *{name}* пишет в семейный чат:\n\n{message}",
        'not_relative': "❌ Вы не привязаны ни к одной семье. Используйте /add_relative.",
        'db_error': "❌ Ошибка базы данных. Попробуйте позже.",
        'weather_unknown_city': "{name}, я пока не знаю ваш город.\nПожалуйста, напишите мне: «Я живу в <город>», и мы добавим это в профиле.",
        'weather_error': "Не получилось получить прогноз погоды сейчас. Попробуйте чуть позже.",
        'weather_forecast': "Доброе утро, {name}!\n\n{summary}\n\nПожалуйста, будьте осторожны и одевайтесь по погоде.",
        'city_remembered': "✅ Запомнила! Ваш город: {city}\n\n🌤️ Теперь узнаю погоду!",
        'games_menu': "🎮 *Игры и викторины*\n\nВыберите игру:",
        'riddle_game': "🔮 *Загадка:*\n\n{question}\n\nНапишите свой ответ:",
        'words_game': "📖 *Игра «Слова»*\n\nПравила: называете слово, следующий игрок называет слово на последнюю букву предыдущего.\nВы начинаете! Напишите любое слово (существительное, именительный падеж).",
        'truth_lie_game': "✅ *Правда или ложь?*\n\n{question}\n\nОтправьте «правда» или «ложь»:",
        'exit_game': "❌ Вы вышли из игры. Возвращайтесь ещё!",
        'riddle_correct': "🎉 Правильно! Отличная работа!\n\nЧтобы сыграть ещё раз, нажмите /games",
        'riddle_wrong': "❌ Неправильно! Правильный ответ: {answer}\n\nСыграйте ещё раз: /games",
        'words_used': "❌ Слово «{word}» уже было! Вы проиграли. Начните новую игру: /games",
        'words_wrong_letter': "❌ Слово должно начинаться на букву «{letter}»! Вы проиграли. Начните новую игру: /games",
        'words_too_short': "❌ Слишком короткое слово! Вы проиграли. Начните новую игру: /games",
        'words_bot_turn': "🤖 Моё слово: {word}\nТеперь ваша очередь на букву «{letter}».",
        'words_win': "🎉 Я не могу найти слово на букву «{letter}»! Вы победили! Поздравляю!\n\nНачать новую игру: /games",
        'truth_lie_prompt': "Пожалуйста, ответьте «правда» или «ложь».",
        'truth_lie_correct': "🎉 Правильно! Отличная эрудиция!\n\nСыграть ещё: /games",
        'truth_lie_wrong': "❌ Неправильно! {question} – это {answer}.\n\nСыграть ещё: /games",
        'voice_processing': "🎤 Слушаю ваше голосовое сообщение...\n\nЭто может занять несколько секунд.",
        'voice_failed': "😔 Не удалось распознать голосовое сообщение.\n\nПопробуйте:\n• Говорить чётче и медленнее\n• Уменьшить фоновый шум\n• Отправить сообщение короче (3-5 секунд)\n\nИли просто напишите текстом! 💬",
        'voice_recognized': "📝 Вы сказали: *\"{text}\"*\n\n🤔 Думаю над ответом...",
        'voice_error': "❌ Произошла ошибка при обработке голосового сообщения.\n\nПожалуйста, попробуйте ещё раз или напишите текстом.",
        'photo_saved': "📸 Фото добавлено в семейный альбом!",
        'video_saved': "🎥 Видео добавлено в семейный альбом!",
        'album_empty': "📭 В семейном альбоме пока нет фотографий или видео.",
        'album_caption': "📅 {date}\n👤 {author}",
        'album_caption_with_text': "📅 {date}\n👤 {author}\n💬 {caption}",
        'health_report': "📊 *Отчёт о здоровье за {days} дней*\n\n💬 Разговоров с ботом: {talks}\n💊 Приёмов лекарств (выполнено): {reminders}\n📈 Процент выполнения: {rate:.1f}%\n🆘 Нажатий SOS: {sos}\n🎤 Голосовых сообщений: {voice}\n\n🏆 *Всего активностей:* {total}",
        'health_report_no_reminders': "📊 *Отчёт о здоровье за {days} дней*\n\n💬 Разговоров с ботом: {talks}\n💊 Приёмов лекарств (выполнено): {reminders}\n🆘 Нажатий SOS: {sos}\n🎤 Голосовых сообщений: {voice}\n\n🏆 *Всего активностей:* {total}",
        'health_recommendation_meds': "\n⚠️ *Рекомендация:* старайтесь не пропускать приём лекарств!",
        'health_recommendation_talk': "\n💡 *Совет:* общайтесь с ботом – это поднимает настроение!",
        'family_report': "👨‍👩‍👧 *Семейный отчёт за {days} дней*\n\n",
        'family_report_member': "👤 *{name}*\n   💬 Разговоров: {talks}\n   💊 Приёмов лекарств: {reminders}\n   🆘 SOS: {sos}\n\n",
        'family_report_total': "📊 *Общая активность семьи:*\n   💬 Всего диалогов: {talks}\n   💊 Всего приёмов: {reminders}\n   🆘 Всего SOS: {sos}\n",
        'member_stats': "📊 *Статистика пользователя {name}* (ID: {id})\n📅 За последние {days} дней:\n\n💬 Разговоров: {talks}\n💊 Приёмов лекарств: {reminders}\n🆘 SOS: {sos}\n🎤 Голосовых: {voice}\n\n🏆 *Всего активностей:* {total}",
        'event_add_date': "📅 *Добавление события*\n\nВведите дату в формате ГГГГ-ММ-ДД (например, 2025-12-31):",
        'event_add_time': "Введите время (опционально) в формате ЧЧ:ММ или '-' пропустить:",
        'event_add_title': "Введите название события (обязательно):",
        'event_add_description': "Введите описание (необязательно, можно '-' пропустить):",
        'event_add_type': "Выберите тип события:\n1 - День рождения\n2 - Праздник\n3 - Встреча\n4 - Другое\n5 - День рождения другого человека",
        'event_add_target': "Введите Telegram ID именинника (или '-' если это ваш день рождения):",
        'event_add_remind': "За сколько дней напомнить? (по умолчанию 1, введите число):",
        'event_add_success': "✅ Событие добавлено!\n\n📅 {date}\n📌 {title}\n🔔 Напомню за {days} дн.",
        'events_list_empty': "📭 У вас нет предстоящих событий.",
        'events_list_title': "📅 *Ваши ближайшие события:*\n",
        'event_birthday_title': "День рождения {name}",
        'event_delete_usage': "❌ Укажите ID события: /delete_event <id>",
        'event_deleted': "✅ Событие {id} удалено.",
        'event_not_found': "❌ Событие не найдено или у вас нет прав.",
        'birthday_greeting': "🎉 *С ДНЁМ РОЖДЕНИЯ!* 🎉\n\nДорогой(ая) *{name}*!\n\nЖелаю здоровья, счастья, радости и тепла!\nПусть каждый день приносит улыбку, а близкие всегда будут рядом! 🌷\n\nС любовью, твой бот-компаньон «Семья» ❤️",
        'birthday_feed': "🎉 Сегодня день рождения у *{name}*! Поздравляем!",
        'birthday_notify': "🎉 *Сегодня день рождения у {name}!* Поздравьте его/её в семейном чате!",
        'help_text': "🤖 *Бот-компаньон «Семья»*\n\nОсновные команды:\n• /start — начать заново\n• /menu — главное меню\n• /help — эта справка\n• /lang — сменить язык\n\n💬 *Общение:*\n• Просто напишите текст – я отвечу через нейросеть\n• 🎤 Отправьте голосовое сообщение – я распознаю и отвечу\n\n📅 *Напоминания:*\n• /add_meds — добавить напоминание о лекарствах\n• /enable_checkin — ежедневный опрос «Как дела?»\n• /disable_checkin — отключить опрос\n\n👨‍👩‍👧 *Семья:*\n• /add_relative <ID> — привязать родственника\n• /family_send <текст> — отправить в семейный чат\n• /family_feed — показать семейную ленту\n• /sos — экстренная помощь\n\n📊 *Аналитика:*\n• /health_report [дни] — мой отчёт о здоровье\n• /family_report [дни] — сводный отчёт по семье\n• /member_stats <ID> [дни] — статистика члена семьи\n\n📅 *Календарь:*\n• /add_event — добавить событие\n• /events_list — список событий\n• /delete_event <id> — удалить событие\n\n🎮 *Игры:*\n• /games — меню игр (загадки, слова, правда/ложь)\n\n📸 *Альбом:*\n• /album — показать семейный альбом\n• Отправьте фото или видео – они сохранятся в альбом\n\n🎂 *Дни рождения:*\n• Добавьте день рождения через /add_event (тип 1 или 5)\n• Бот автоматически поздравит именинника в 9:00\n\n🌤️ *Погода:*\n• /weather — погода (нужно указать город)\n• Напишите «мой город Москва» – запомню\n\n🆘 *Помощь:*\n• /companions — поиск компаньонов\n• /volunteers — волонтёрская помощь\n• /health_extra — советы по здоровью\n• /helper — помощь по дому\n• /nostalgia — ностальгия\n• /courses — курсы\n• /achievements — достижения\n• /admin_stats — аналитика (для админов)",
    },
    'en': {
        'start': "Hello! I'm 'Family' companion bot 🏡\n\nLet's get acquainted.\nWho are you?\n\n➤ I'm an elderly user\n➤ I'm a relative/guardian",
        'choose_role': "Okay! You are a relative.\nPlease enter the binding code we will give to your loved one.",
        'senior_name': "Nice to meet you! 🌷 What's your name?\n\nPlease write how to address you.",
        'senior_age': "Nice to meet you, {name}!\n\nHow old are you?",
        'senior_city': "Thank you!\n\nWhat city do you live in?",
        'senior_interests': "Great!\n\nTell me what you like to do? For example: garden, books, movies, knitting, chess...",
        'senior_complete': "Thank you, {name}! I remember everything.\n\nNow you can use me as a companion.\n\nHere's the main menu:",
        'relative_complete': "Thank you! Code accepted.\n\nHere's the main menu:",
        'lang_changed': "✅ Language changed to English",
        'lang_usage': "📝 Usage: /lang ru or /lang en",
        'lang_invalid': "❌ Supported languages: ru, en",
        'menu': "📋 Main menu:",
        'talk_placeholder': "Write something! 😊",
        'no_reminders': "📋 You have no reminders yet.\n\nI can remind you about medications daily.\nSend /add_meds to add a reminder.",
        'reminders_list': "📋 Your reminders:",
        'add_reminder_prompt': "When to remind about medication?\nWrite time in HH:MM format, e.g., 09:00 or 21:30.",
        'add_reminder_time_invalid': "Please enter time in HH:MM format, e.g., 08:30.",
        'add_reminder_text_prompt': "What should I remind?\nExample: «Take blood pressure pill».",
        'add_reminder_success': "Okay, I will remind you daily at {time}: «{text}».\n\nYou can always view your reminders via the «📅 Reminders» button.",
        'add_reminder_cancel': "Reminder setup cancelled.",
        'sos_sent': "You pressed SOS. I have recorded this event and will notify your loved ones if possible.",
        'sos_notification': "Attention.\n\nYour loved one (Telegram ID {id}) pressed the SOS button in the «Family» bot.\nPlease contact them as soon as possible.",
        'sos_feed': "SOS button pressed!",
        'sos_notify_family': "🚨 *{name}* pressed SOS! Please check the family feed.",
        'family_feed_empty': "📭 No messages in the family feed yet.",
        'family_feed_title': "📋 *Family feed:*\n",
        'family_send_usage': "📝 Usage: /family_send <message text>",
        'family_send_success': "✅ Message sent to family feed!",
        'family_send_notify': "📢 *{name}* writes in family chat:\n\n{message}",
        'not_relative': "❌ You are not linked to any family. Use /add_relative.",
        'db_error': "❌ Database error. Please try again later.",
        'weather_unknown_city': "{name}, I don't know your city yet.\nPlease tell me: «I live in Moscow» and I will remember it.",
        'weather_error': "Could not get weather forecast now. Please try later.",
        'weather_forecast': "Good morning, {name}!\n\n{summary}\n\nPlease be careful and dress according to the weather.",
        'city_remembered': "✅ Remembered! Your city: {city}\n\n🌤️ Now you can ask for weather!",
        'games_menu': "🎮 *Games and quizzes*\n\nChoose a game:",
        'riddle_game': "🔮 *Riddle:*\n\n{question}\n\nWrite your answer:",
        'words_game': "📖 *Word game*\n\nRules: you say a word, next player says a word starting with the last letter of the previous word.\nYou start! Write any word (noun, nominative case).",
        'truth_lie_game': "✅ *Truth or lie?*\n\n{question}\n\nReply «truth» or «lie»:",
        'exit_game': "❌ You left the game. Come back again!",
        'riddle_correct': "🎉 Correct! Great job!\n\nTo play again, press /games",
        'riddle_wrong': "❌ Wrong! Correct answer: {answer}\n\nPlay again: /games",
        'words_used': "❌ Word «{word}» has already been used! You lost. Start a new game: /games",
        'words_wrong_letter': "❌ Word must start with letter «{letter}»! You lost. Start a new game: /games",
        'words_too_short': "❌ Word too short! You lost. Start a new game: /games",
        'words_bot_turn': "🤖 My word: {word}\nNow your turn with letter «{letter}».",
        'words_win': "🎉 I can't find a word starting with «{letter}»! You win! Congratulations!\n\nStart a new game: /games",
        'truth_lie_prompt': "Please answer «truth» or «lie».",
        'truth_lie_correct': "🎉 Correct! Great erudition!\n\nPlay again: /games",
        'truth_lie_wrong': "❌ Wrong! {question} – it's {answer}.\n\nPlay again: /games",
        'voice_processing': "🎤 Listening to your voice message...\n\nThis may take a few seconds.",
        'voice_failed': "😔 Could not recognize the voice message.\n\nTry:\n• Speak more clearly and slowly\n• Reduce background noise\n• Send a shorter message (3-5 seconds)\n\nOr just write text! 💬",
        'voice_recognized': "📝 You said: *\"{text}\"*\n\n🤔 Thinking...",
        'voice_error': "❌ An error occurred while processing the voice message.\n\nPlease try again or write text.",
        'photo_saved': "📸 Photo added to family album!",
        'video_saved': "🎥 Video added to family album!",
        'album_empty': "📭 No photos or videos in the family album yet.",
        'album_caption': "📅 {date}\n👤 {author}",
        'album_caption_with_text': "📅 {date}\n👤 {author}\n💬 {caption}",
        'health_report': "📊 *Health report for last {days} days*\n\n💬 Conversations with bot: {talks}\n💊 Medications taken: {reminders}\n📈 Completion rate: {rate:.1f}%\n🆘 SOS presses: {sos}\n🎤 Voice messages: {voice}\n\n🏆 *Total activities:* {total}",
        'health_report_no_reminders': "📊 *Health report for last {days} days*\n\n💬 Conversations with bot: {talks}\n💊 Medications taken: {reminders}\n🆘 SOS presses: {sos}\n🎤 Voice messages: {voice}\n\n🏆 *Total activities:* {total}",
        'health_recommendation_meds': "\n⚠️ *Recommendation:* try not to miss medication!",
        'health_recommendation_talk': "\n💡 *Advice:* chat with the bot – it boosts your mood!",
        'family_report': "👨‍👩‍👧 *Family report for last {days} days*\n\n",
        'family_report_member': "👤 *{name}*\n   💬 Conversations: {talks}\n   💊 Medications taken: {reminders}\n   🆘 SOS presses: {sos}\n\n",
        'family_report_total': "📊 *Total family activity:*\n   💬 Total conversations: {talks}\n   💊 Total medications: {reminders}\n   🆘 Total SOS: {sos}\n",
        'member_stats': "📊 *Statistics of user {name}* (ID: {id})\n📅 Last {days} days:\n\n💬 Conversations: {talks}\n💊 Medications taken: {reminders}\n🆘 SOS: {sos}\n🎤 Voice: {voice}\n\n🏆 *Total activities:* {total}",
        'event_add_date': "📅 *Add event*\n\nEnter date in YYYY-MM-DD format (e.g., 2025-12-31):",
        'event_add_time': "Enter time (optional) in HH:MM format or '-' to skip:",
        'event_add_title': "Enter event title (required):",
        'event_add_description': "Enter description (optional, '-' to skip):",
        'event_add_type': "Select event type:\n1 - Birthday\n2 - Holiday\n3 - Meeting\n4 - Other\n5 - Someone else's birthday",
        'event_add_target': "Enter Telegram ID of the birthday person (or '-' if it's your birthday):",
        'event_add_remind': "How many days in advance to remind? (default 1, enter number):",
        'event_add_success': "✅ Event added!\n\n📅 {date}\n📌 {title}\n🔔 Will remind in {days} day(s).",
        'events_list_empty': "📭 You have no upcoming events.",
        'events_list_title': "📅 *Your upcoming events:*\n",
        'event_birthday_title': "Birthday of {name}",
        'event_delete_usage': "❌ Specify event ID: /delete_event <id>",
        'event_deleted': "✅ Event {id} deleted.",
        'event_not_found': "❌ Event not found or you don't have permission.",
        'birthday_greeting': "🎉 *HAPPY BIRTHDAY!* 🎉\n\nDear *{name}*!\n\nI wish you health, happiness, joy and warmth!\nMay every day bring a smile, and may your loved ones always be by your side! 🌷\n\nWith love, your companion bot «Family» ❤️",
        'birthday_feed': "🎉 Today is *{name}*'s birthday! Congratulations!",
        'birthday_notify': "🎉 *Today is {name}'s birthday!* Congratulate them in the family chat!",
        'help_text': "🤖 *Family companion bot*\n\nMain commands:\n• /start — start over\n• /menu — main menu\n• /help — this help\n• /lang — change language\n\n💬 *Communication:*\n• Just write text – I'll reply via AI\n• 🎤 Send a voice message – I'll recognize and reply\n\n📅 *Reminders:*\n• /add_meds — add medication reminder\n• /enable_checkin — daily «How are you?» survey\n• /disable_checkin — disable survey\n\n👨‍👩‍👧 *Family:*\n• /add_relative <ID> — link a relative\n• /family_send <text> — send to family chat\n• /family_feed — show family feed\n• /sos — emergency help\n\n📊 *Analytics:*\n• /health_report [days] — my health report\n• /family_report [days] — family summary report\n• /member_stats <ID> [days] — family member statistics\n\n📅 *Calendar:*\n• /add_event — add event\n• /events_list — list events\n• /delete_event <id> — delete event\n\n🎮 *Games:*\n• /games — game menu (riddles, words, truth/lie)\n\n📸 *Album:*\n• /album — show family album\n• Send a photo or video – they will be saved to the album\n\n🎂 *Birthdays:*\n• Add a birthday via /add_event (type 1 or 5)\n• The bot will automatically congratulate the birthday person at 9:00\n\n🌤️ *Weather:*\n• /weather — weather (need to specify city)\n• Write «my city Moscow» – I'll remember\n\n🆘 *Help:*\n• /companions — find companions\n• /volunteers — volunteer help\n• /health_extra — health tips\n• /helper — home help\n• /nostalgia — nostalgia\n• /courses — courses\n• /achievements — achievements\n• /admin_stats — analytics (for admins)",
    }
}

def get_text(lang: str, key: str, **kwargs) -> str:
    """Возвращает текст на нужном языке с подстановкой параметров."""
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
            ["📸 Album", "❓ Help"],
        ]
    else:
        buttons = [
            ["💬 Поговорить", "📅 Напоминания"],
            ["👥 События", "🆘 ПОМОЩЬ"],
            ["👨‍👩‍👧 Семья", "⚙️ Настройки"],
            ["🎮 Игры", "🌤️ Погода"],
            ["📸 Альбом", "❓ Помощь"],
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

class EventState(Enum):
    DATE = 1
    TIME = 2
    TITLE = 3
    DESCRIPTION = 4
    TYPE = 5
    TARGET_USER = 6
    REMIND_DAYS = 7


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
async def get_user_lang(update: Update) -> str:
    """Определяет язык пользователя (из БД или из Telegram)."""
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    if not lang:
        # Пытаемся определить по языку Telegram
        if update.effective_user and update.effective_user.language_code:
            if update.effective_user.language_code.startswith('ru'):
                lang = 'ru'
            else:
                lang = 'en'
        else:
            lang = 'ru'
        set_user_language(user_id, lang)
    return lang


# ==================== ОНБОРДИНГ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    text = get_text(lang, 'start')
    keyboard = [["Я пользователь", "Я родственник"]]
    if lang == 'en':
        keyboard = [["Elderly user", "Relative"]]
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
        await update.message.reply_text(
            get_text(lang, 'choose_role'),
            reply_markup=ReplyKeyboardRemove(),
        )
        return OnboardingState.RELATIVE_CODE.value
    context.user_data["role"] = Role.SENIOR.value
    await update.message.reply_text(
        get_text(lang, 'senior_name'),
        reply_markup=ReplyKeyboardRemove(),
    )
    return OnboardingState.SENIOR_NAME.value

async def senior_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    context.user_data["name"] = (update.message.text or "").strip()
    await update.message.reply_text(
        get_text(lang, 'senior_age', name=context.user_data["name"])
    )
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
    name_for_text = name or "друг" if lang == 'ru' else "friend"
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


# ==================== ОСНОВНЫЕ ОБРАБОТЧИКИ ====================
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
    lines.append(f"💬 {get_text(lang, 'talks') if lang == 'ru' else 'Conversations'}: {talk}")
    lines.append(f"💊 {get_text(lang, 'medications_taken') if lang == 'ru' else 'Medications taken'}: {meds_done}")
    lines.append(f"🆘 SOS: {sos}")
    lines.append("\n" + ("Позже здесь появится общий семейный чат" if lang == 'ru' else "Family chat will appear here later"))
    await update.message.reply_text("\n".join(lines))

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await get_user_lang(update)
    await update.message.reply_text(
        get_text(lang, 'help_text')  # кратко, но можно вывести список команд
    )

async def fallback_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_talk(update, context)


# ---------- Напоминания о лекарствах ----------
async def add_meds_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = await get_user_lang(update)
    await update.message.reply_text(
        get_text(lang, 'add_reminder_prompt'),
        reply_markup=ReplyKeyboardRemove(),
    )
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
    text = job.data.get("text", "Пора принять лекарство." if get_user_language(chat_id) == 'ru' else "Time to take medication.")
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
    await update.message.reply_text(
        get_text(lang, 'add_reminder_cancel'),
        reply_markup=get_main_menu_keyboard(lang),
    )
    return ConversationHandler.END


# ---------- Ежедневная проверка «Как дела?» ----------
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
    job_queue.run_daily(
        daily_checkin,
        time=time(hour=10, minute=0),
        chat_id=chat_id,
        name=f"checkin-{chat_id}",
    )
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


# ---------- Привязка родственника ----------
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


# ---------- Семейная лента ----------
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


# ---------- Календарь событий ----------
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


# ---------- Аналитика и отчёты ----------
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
            days=days,
            talks=stats['talks'],
            reminders=stats['reminders_done'],
            rate=reminder_stats['completion_rate'],
            sos=stats['sos'],
            voice=stats['voice'],
            total=stats['total'])
    else:
        report = get_text(lang, 'health_report_no_reminders',
            days=days,
            talks=stats['talks'],
            reminders=stats['reminders_done'],
            sos=stats['sos'],
            voice=stats['voice'],
            total=stats['total'])
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
    total_talks = 0
    total_reminders = 0
    total_sos = 0
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
    lang = await get_user_lang(update)
    await update.message.reply_text(
        get_text(lang, 'games_menu'),
        reply_markup=get_games_menu_keyboard(lang),
        parse_mode="Markdown"
    )

async def play_riddle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    riddle = random.choice(RIDDLES)
    save_game_state(user_id, "riddle", json.dumps({"question": riddle[0], "answer": riddle[1]}))
    await update.message.reply_text(
        get_text(lang, 'riddle_game', question=riddle[0]),
        parse_mode="Markdown"
    )

async def play_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    save_game_state(user_id, "words", json.dumps({"last_letter": None, "used_words": []}))
    await update.message.reply_text(
        get_text(lang, 'words_game'),
        parse_mode="Markdown"
    )

async def play_truth_or_lie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    question, answer = random.choice(TRUTH_OR_LIE)
    save_game_state(user_id, "truth_or_lie", json.dumps({"question": question, "answer": answer}))
    await update.message.reply_text(
        get_text(lang, 'truth_lie_game', question=question),
        parse_mode="Markdown"
    )

async def exit_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = await get_user_lang(update)
    clear_game_state(user_id)
    await update.message.reply_text(
        get_text(lang, 'exit_game'),
        reply_markup=get_main_menu_keyboard(lang),
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
    lang = await get_user_lang(update)
    state = get_game_state(user_id)
    if not state:
        return
    game_name = state["game_name"]
    game_data = json.loads(state["game_data"])
    answer = update.message.text.strip().lower()
    
    if game_name == "riddle":
        correct_answer = game_data["answer"]
        if answer == correct_answer or answer in correct_answer:
            await update.message.reply_text(get_text(lang, 'riddle_correct'), reply_markup=get_main_menu_keyboard(lang))
        else:
            await update.message.reply_text(get_text(lang, 'riddle_wrong', answer=correct_answer), reply_markup=get_main_menu_keyboard(lang))
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
        last_letter = answer[-1]
        save_game_state(user_id, "words", json.dumps({"last_letter": last_letter, "used_words": list(used_words)}))
        
        bot_word = find_word_on_letter(last_letter, used_words)
        if bot_word:
            used_words.add(bot_word)
            new_last_letter = bot_word[-1]
            save_game_state(user_id, "words", json.dumps({"last_letter": new_last_letter, "used_words": list(used_words)}))
            await update.message.reply_text(get_text(lang, 'words_bot_turn', word=bot_word, letter=new_last_letter))
        else:
            await update.message.reply_text(get_text(lang, 'words_win', letter=last_letter), reply_markup=get_main_menu_keyboard(lang))
            clear_game_state(user_id)
    
    elif game_name == "truth_or_lie":
        is_true = answer in ["правда", "верно", "да", "true", "truth"]
        is_false = answer in ["ложь", "неправда", "нет", "false", "lie"]
        
        if not (is_true or is_false):
            await update.message.reply_text(get_text(lang, 'truth_lie_prompt'))
            return
        
        correct = game_data["answer"]
        if (is_true and correct) or (is_false and not correct):
            await update.message.reply_text(get_text(lang, 'truth_lie_correct'), reply_markup=get_main_menu_keyboard(lang))
        else:
            await update.message.reply_text(get_text(lang, 'truth_lie_wrong', question=game_data["question"], answer='правда' if correct else 'ложь'), reply_markup=get_main_menu_keyboard(lang))
        clear_game_state(user_id)


# ---------- Голосовые сообщения ----------
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
        
        await processing_msg.delete()
        await update.message.reply_text(reply, reply_markup=get_main_menu_keyboard(lang))
        
        if user:
            log_activity(user.id, "voice")
            
    except Exception as e:
        logger.error(f"Voice handling error: {e}")
        await processing_msg.edit_text(get_text(lang, 'voice_error'), reply_markup=get_main_menu_keyboard(lang))


# ---------- Медиафайлы ----------
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


# ---------- Дни рождения ----------
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


# ---------- Команда смены языка ----------
async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("📝 Использование: /lang ru или /lang en" if get_user_language(user_id) == 'ru' else "📝 Usage: /lang ru or /lang en")
        return
    new_lang = context.args[0].lower()
    if new_lang not in ['ru', 'en']:
        await update.message.reply_text("❌ Поддерживаются языки: ru, en" if get_user_language(user_id) == 'ru' else "❌ Supported languages: ru, en")
        return
    set_user_language(user_id, new_lang)
    await update.message.reply_text(get_text(new_lang, 'lang_changed'), reply_markup=get_main_menu_keyboard(new_lang))


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
    lang = await get_user_lang(update)
    clear_chat_history(user_id)
    await update.message.reply_text("🧹 История диалогов очищена!" if lang == 'ru' else "🧹 Chat history cleared!", reply_markup=get_main_menu_keyboard(lang))


# ---------- Навигация ----------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await get_user_lang(update)
    await update.message.reply_text(get_text(lang, 'help_text'), parse_mode="Markdown", reply_markup=get_main_menu_keyboard(lang))

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await get_user_lang(update)
    await update.message.reply_text(get_text(lang, 'menu'), reply_markup=get_main_menu_keyboard(lang))


# ---------- Погода ----------
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
    await update.message.reply_text(
        get_text(lang, 'weather_forecast', name=name, summary=summary),
        reply_markup=get_main_menu_keyboard(lang),
    )


# ---------- Установка города ----------
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


# ==================== ПОСТРОЕНИЕ ПРИЛОЖЕНИЯ ====================
def build_application():
    settings = get_settings()
    init_db()
    init_chat_history_table()
    init_family_feed_table()
    init_calendar_table()
    init_games_table()
    init_media_table()

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

    # Напоминания о лекарствах
    meds_conv = ConversationHandler(
        entry_points=[CommandHandler("add_meds", add_meds_start)],
        states={
            MedsState.ASK_TIME.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_time)],
            MedsState.ASK_TEXT.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_meds_text)],
        },
        fallbacks=[CommandHandler("cancel", meds_cancel)],
    )
    application.add_handler(meds_conv)

    # Календарь событий
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

    # Основные команды
    application.add_handler(CommandHandler("weather", weather_command))
    application.add_handler(CommandHandler("enable_checkin", enable_checkin))
    application.add_handler(CommandHandler("disable_checkin", disable_checkin))
    application.add_handler(CommandHandler("voice_help", voice_help))
    application.add_handler(CommandHandler("add_relative", add_relative_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("menu", menu_cmd))
    application.add_handler(CommandHandler("clear_history", clear_history_cmd))
    application.add_handler(CommandHandler("lang", lang_command))

    # Семейная лента
    application.add_handler(CommandHandler("family_send", family_send))
    application.add_handler(CommandHandler("family_feed", family_feed))

    # Календарь
    application.add_handler(CommandHandler("events_list", events_list))
    application.add_handler(CommandHandler("delete_event", delete_event_cmd))

    # Аналитика
    application.add_handler(CommandHandler("health_report", health_report))
    application.add_handler(CommandHandler("family_report", family_report))
    application.add_handler(CommandHandler("member_stats", member_stats))

    # Игры
    application.add_handler(CommandHandler("games", games_menu))
    application.add_handler(MessageHandler(filters.Regex("^🔮 Загадка$|^🔮 Riddle$"), play_riddle))
    application.add_handler(MessageHandler(filters.Regex("^📖 Слова$|^📖 Words$"), play_words))
    application.add_handler(MessageHandler(filters.Regex("^✅ Правда или ложь$|^✅ Truth or Lie$"), play_truth_or_lie))
    application.add_handler(MessageHandler(filters.Regex("^❌ Выйти из игры$|^❌ Exit game$"), exit_game))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_game_answer), group=1)

    # Голосовые и медиа
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(CommandHandler("album", show_album))

    # Дополнительные команды
    for cmd in [
        companions_cmd, volunteers_cmd, health_extra_cmd, helper_cmd,
        nostalgia_cmd, courses_cmd, achievements_cmd, admin_analytics_cmd
    ]:
        application.add_handler(CommandHandler(cmd.__name__.replace("_cmd", ""), cmd))

    # Установка города (обработка фразы)
    application.add_handler(MessageHandler(filters.Regex(r'(мой город|живу в|город|my city|i live in)'), set_city))

    # Маршрутизация главного меню
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_router), group=2)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_text), group=3)

    # Ежедневные задачи
    job_queue = application.job_queue
    if job_queue:
        async def daily_event_reminder(context: ContextTypes.DEFAULT_TYPE):
            today = date.today()
            today_events = get_events_by_date(today.isoformat())
            for ev in today_events:
                time_msg = f" в {ev['time']}" if ev['time'] else ""
                lang = get_user_language(ev['user_id'])
                text = f"🔔 *Напоминание о событии сегодня{time_msg}:*\n{ev['title']}\n{ev['description'] or ''}"
                await context.bot.send_message(chat_id=ev['user_id'], text=text, parse_mode="Markdown")
            tomorrow = today + timedelta(days=1)
            tomorrow_events = get_events_by_date(tomorrow.isoformat())
            for ev in tomorrow_events:
                if ev['remind_before_days'] >= 1:
                    lang = get_user_language(ev['user_id'])
                    text = f"📅 *Напоминание:* завтра событие «{ev['title']}»."
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
