import os
import logging
import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse
from starlette.routing import Route
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

# Импортируем всю логику из вашего bot_main
from bot_main import (
    build_application, get_settings, logger, 
    MAIN_MENU_KEYBOARD, start, handle_talk, fallback_text
)

# Настройки
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
URL = os.environ["RENDER_EXTERNAL_URL"]  # Render выдаёт автоматически
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Создаём приложение Telegram
app = build_application()

async def health(_):
    """Health check endpoint для Render"""
    return PlainTextResponse("OK")

async def telegram_webhook(request):
    """Endpoint для веб-хука Telegram"""
    try:
        data = await request.json()
        update = Update.de_json(data, app.bot)
        await app.update_queue.put(update)
        return Response()
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return Response(status_code=500)

# Starlette приложение
starlette_app = Starlette(routes=[
    Route("/health", health, methods=["GET"]),
    Route(f"/webhook/{TOKEN}", telegram_webhook, methods=["POST"]),
])

async def setup_webhook():
    """Установка веб-хука при запуске"""
    webhook_url = f"{URL}/webhook/{TOKEN}"
    await app.bot.set_webhook(webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

async def startup():
    """Запуск приложения и установка веб-хука"""
    await app.initialize()
    await app.start()
    await setup_webhook()

async def shutdown():
    """Остановка приложения"""
    await app.stop()

if __name__ == "__main__":
    # Регистрируем обработчики старта/остановки
    starlette_app.add_event_handler("startup", startup)
    starlette_app.add_event_handler("shutdown", shutdown)
    
    # Запускаем сервер
    uvicorn.run(
        starlette_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
