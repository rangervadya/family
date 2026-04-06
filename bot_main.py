import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Простая клавиатура
menu = ReplyKeyboardMarkup(
    [["💬 Поговорить", "📅 Напоминания"], ["🆘 SOS", "👨‍👩‍👧 Семья"]],
    resize_keyboard=True,
)

async def start(update: Update, context):
    await update.message.reply_text(
        "👋 Привет! Я бот-компаньон «Семья»!\n\n"
        "Вот главное меню:",
        reply_markup=menu
    )

async def help_command(update: Update, context):
    await update.message.reply_text(
        "🤖 Команды:\n"
        "/start - начать\n"
        "/help - помощь\n\n"
        "Просто пиши мне!",
        reply_markup=menu
    )

async def handle_message(update: Update, context):
    text = update.message.text
    logger.info(f"Получено сообщение: {text}")
    
    # Простой ответ
    await update.message.reply_text(
        f"✅ Я получил ваше сообщение!\n\n"
        f"Вы написали: {text}\n\n"
        f"Скоро я научусь отвечать умнее! 😊",
        reply_markup=menu
    )

async def handle_voice(update: Update, context):
    await update.message.reply_text(
        "🎤 Я получил голосовое сообщение!\n\n"
        "Пожалуйста, напишите текстом, так я лучше понимаю! 😊",
        reply_markup=menu
    )

def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не задан!")
        return
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ Бот запущен и работает!")
    app.run_polling()

if __name__ == "__main__":
    main()
