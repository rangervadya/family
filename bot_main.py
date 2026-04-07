import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

async def start(update: Update, context):
    logger.info(f"Команда /start от пользователя {update.effective_user.id}")
    await update.message.reply_text("👋 Привет! Я бот-компаньон!")

async def handle_message(update: Update, context):
    logger.info(f"Получено сообщение: {update.message.text}")
    await update.message.reply_text(f"✅ Я получил: {update.message.text}")

def main():
    if not TOKEN:
        logger.error("TOKEN не задан!")
        return
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
