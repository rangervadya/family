import os
import logging
import uvicorn
import requests
from starlette.applications import Starlette
from starlette.responses import Response, PlainTextResponse, JSONResponse
from starlette.routing import Route
from starlette.requests import Request
from telegram import Update
from telegram.ext import Application
from bot_main import build_application

# Настройки
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
VK_TOKEN = os.environ.get("VK_GROUP_TOKEN", "")
VK_CONFIRMATION_CODE = os.environ.get("VK_CONFIRMATION_CODE", "e1388965")  # Обновленный код
URL = os.environ.get("RENDER_EXTERNAL_URL", "https://family-bot-hr1w.onrender.com")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Создаём приложение Telegram
telegram_app = build_application() if TELEGRAM_TOKEN else None

async def root(request: Request) -> JSONResponse:
    """Корневой маршрут для Render"""
    return JSONResponse({
        "status": "ok",
        "service": "Family Bot",
        "endpoints": {
            "health": "/health",
            "telegram": "/telegram_webhook",
            "vk": "/vk"
        }
    })

async def health(request: Request) -> PlainTextResponse:
    """Health check endpoint для Render"""
    return PlainTextResponse("OK")

async def telegram_webhook(request: Request) -> Response:
    """Endpoint для веб-хука Telegram"""
    if not TELEGRAM_TOKEN or not telegram_app:
        return Response(status_code=404)
    
    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.update_queue.put(update)
        return Response()
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return Response(status_code=500)

async def vk_webhook(request: Request) -> Response:
    """Endpoint для Callback API ВКонтакте"""
    logger.info(f"VK webhook called with method: {request.method}")
    
    # Проверяем, что это POST-запрос
    if request.method != "POST":
        logger.warning(f"Wrong method: {request.method}")
        return PlainTextResponse("Method not allowed", status_code=405)
    
    if not VK_TOKEN:
        logger.warning("VK_GROUP_TOKEN not set")
        return Response(status_code=404)
    
    try:
        # Получаем данные из запроса
        data = await request.json()
        logger.info(f"VK webhook received: {data}")
        
        # 1. Обработка подтверждения адреса
        if data.get('type') == 'confirmation':
            logger.info(f"Sending confirmation code: {VK_CONFIRMATION_CODE}")
            # Возвращаем ТОЛЬКО строку подтверждения
            return PlainTextResponse(VK_CONFIRMATION_CODE, status_code=200)
        
        # 2. Обработка нового сообщения
        if data.get('type') == 'message_new':
            message_obj = data.get('object', {}).get('message', {})
            user_message = message_obj.get('text', '').strip().lower()
            user_id = message_obj.get('from_id')
            peer_id = message_obj.get('peer_id')
            
            logger.info(f"New VK message from {user_id}: {user_message}")
            
            # Обработка команды start
            if user_message in ['/start', 'начать', 'start', 'привет', 'здравствуй']:
                answer_text = (
                    "🌷 Здравствуйте! Я бот-компаньон «Семья».\n\n"
                    "Я помогу вам:\n"
                    "• 💬 Поддержать разговор\n"
                    "• 📅 Напомнить о важном\n"
                    "• 👥 Рассказать о событиях\n"
                    "• 🆘 Отправить сигнал SOS близким\n\n"
                    "Просто напишите мне любое сообщение, и мы начнём общение!"
                )
            else:
                answer_text = (
                    f"Вы написали: {user_message}\n\n"
                    "🤖 Я бот-компаньон «Семья».\n\n"
                    "📌 Что я умею:\n"
                    "• Напишите «Начать» или «/start» — получить приветствие\n"
                    "• Расскажите о себе — я запомню\n"
                    "• Спросите о погоде — я подскажу\n\n"
                    "✨ Скоро я научусь отвечать умнее!"
                )
            
            # Отправляем ответ
            send_vk_message(peer_id or user_id, answer_text)
        
        return Response(status_code=200)
        
    except Exception as e:
        logger.error(f"VK webhook error: {e}")
        return Response(status_code=500)

def send_vk_message(peer_id: int, message: str) -> None:
    """Отправляет сообщение пользователю ВКонтакте"""
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
        if response.status_code == 200:
            result = response.json()
            if result.get('error'):
                logger.error(f"VK API error: {result['error']}")
            else:
                logger.info(f"VK message sent successfully to {peer_id}")
        else:
            logger.error(f"VK HTTP error: {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to send VK message: {e}")

async def setup_telegram_webhook() -> None:
    """Установка веб-хука для Telegram"""
    if not TELEGRAM_TOKEN or not telegram_app:
        logger.warning("Telegram not configured, skipping webhook setup")
        return
    
    webhook_url = f"{URL}/telegram_webhook"
    result = await telegram_app.bot.set_webhook(webhook_url)
    if result:
        logger.info(f"✅ Telegram webhook set to {webhook_url}")
    else:
        logger.error(f"❌ Failed to set Telegram webhook to {webhook_url}")

async def startup() -> None:
    """Запуск приложений и установка веб-хуков"""
    logger.info("=" * 50)
    logger.info("Starting server...")
    logger.info(f"URL: {URL}")
    logger.info(f"Port: {PORT}")
    logger.info("=" * 50)
    
    if TELEGRAM_TOKEN and telegram_app:
        await telegram_app.initialize()
        await telegram_app.start()
        await setup_telegram_webhook()
        logger.info("✅ Telegram bot started")
    else:
        logger.warning("⚠️ Telegram bot disabled (no token)")
    
    if VK_TOKEN:
        logger.info("✅ VK bot configured")
        logger.info(f"   Webhook URL: {URL}/vk")
        logger.info(f"   Confirmation code: {VK_CONFIRMATION_CODE}")
    else:
        logger.warning("⚠️ VK bot disabled (no token)")
    
    logger.info("Startup complete")
    logger.info("=" * 50)

async def shutdown() -> None:
    """Остановка приложений"""
    logger.info("Shutting down...")
    if TELEGRAM_TOKEN and telegram_app:
        await telegram_app.stop()
        logger.info("Telegram bot stopped")
    logger.info("Shutdown complete")

# Создаём Starlette приложение с маршрутами
# ВАЖНО: маршрут /vk должен принимать только POST
starlette_app = Starlette(routes=[
    Route("/", root, methods=["GET"]),
    Route("/health", health, methods=["GET", "HEAD"]),
    Route("/telegram_webhook", telegram_webhook, methods=["POST"]),
    Route("/vk", vk_webhook, methods=["POST"]),  # Только POST
])

starlette_app.add_event_handler("startup", startup)
starlette_app.add_event_handler("shutdown", shutdown)

if __name__ == "__main__":
    logger.info(f"Starting Uvicorn server on 0.0.0.0:{PORT}")
    uvicorn.run(
        starlette_app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
