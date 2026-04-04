import os
import logging
import uvicorn
import json
import requests
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse
from starlette.routing import Route
from telegram import Update
from telegram.ext import Application, ContextTypes
from bot_main import build_application, logger as bot_logger

# Настройки
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
VK_TOKEN = os.environ.get("VK_GROUP_TOKEN", "")
VK_CONFIRMATION_CODE = os.environ.get("VK_CONFIRMATION_CODE", "")
URL = os.environ.get("RENDER_EXTERNAL_URL", "https://family-bot-hr1w.onrender.com")
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Создаём приложение Telegram
telegram_app = build_application()

async def health(request):
    """Health check endpoint для Render"""
    return PlainTextResponse("OK")

async def telegram_webhook(request):
    """Endpoint для веб-хука Telegram"""
    if not TOKEN:
        return Response(status_code=404)
    
    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.update_queue.put(update)
        return Response()
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return Response(status_code=500)

async def vk_webhook(request):
    """Endpoint для Callback API ВКонтакте"""
    if not VK_TOKEN:
        return Response(status_code=404)
    
    try:
        data = await request.json()
        logger.info(f"VK webhook received: {data}")
        
        # 1. Проверка подтверждения адреса
        if data.get('type') == 'confirmation':
            logger.info("Sending confirmation code to VK")
            return PlainTextResponse(VK_CONFIRMATION_CODE)
        
        # 2. Обработка нового сообщения
        if data.get('type') == 'message_new':
            user_message = data['object']['message'].get('text', '')
            user_id = data['object']['message'].get('from_id')
            peer_id = data['object']['message'].get('peer_id')
            
            logger.info(f"New VK message from {user_id}: {user_message}")
            
            # Логика ответа (простой echo для теста)
            answer_text = f"Вы написали: {user_message}\n\nЯ бот-компаньон. Пока я умею только повторять ваши сообщения."
            
            # Отправляем ответ
            send_vk_message(peer_id or user_id, answer_text)
        
        return Response(status_code=200)
        
    except Exception as e:
        logger.error(f"VK webhook error: {e}")
        return Response(status_code=500)

def send_vk_message(peer_id, message):
    """Отправляет сообщение пользователю ВК"""
    url = 'https://api.vk.com/method/messages.send'
    params = {
        'peer_id': peer_id,
        'message': message,
        'random_id': 0,
        'access_token': VK_TOKEN,
        'v': '5.199',
    }
    try:
        response = requests.post(url, params=params)
        logger.info(f"VK response: {response.text}")
    except Exception as e:
        logger.error(f"Failed to send VK message: {e}")

async def setup_telegram_webhook():
    """Установка веб-хука для Telegram"""
    if not TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set, skipping webhook setup")
        return
    
    webhook_url = f"{URL}/telegram_webhook"
    await telegram_app.bot.set_webhook(webhook_url)
    logger.info(f"Telegram webhook set to {webhook_url}")

async def startup():
    """Запуск приложений и установка веб-хуков"""
    logger.info("Starting up...")
    
    # Запускаем Telegram приложение
    if TOKEN:
        await telegram_app.initialize()
        await telegram_app.start()
        await setup_telegram_webhook()
        logger.info("Telegram bot started")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set, Telegram bot disabled")
    
    logger.info("Startup complete")

async def shutdown():
    """Остановка приложений"""
    logger.info("Shutting down...")
    if TOKEN:
        await telegram_app.stop()
        logger.info("Telegram bot stopped")
    logger.info("Shutdown complete")

# Создаём Starlette приложение с маршрутами
starlette_app = Starlette(routes=[
    Route("/health", health, methods=["GET"]),
    Route("/telegram_webhook", telegram_webhook, methods=["POST"]),
    Route("/vk", vk_webhook, methods=["POST"]),
])

# Регистрируем обработчики старта/остановки
starlette_app.add_event_handler("startup", startup)
starlette_app.add_event_handler("shutdown", shutdown)

if __name__ == "__main__":
    logger.info(f"Starting server on port {PORT}")
    logger.info(f"Health check: {URL}/health")
    logger.info(f"Telegram webhook: {URL}/telegram_webhook")
    logger.info(f"VK webhook: {URL}/vk")
    
    uvicorn.run(
        starlette_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
