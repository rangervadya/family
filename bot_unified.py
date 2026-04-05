import os
import asyncio
import threading
import logging
from flask import Flask, request

# Импортируем Telegram бота
from bot_main import build_application

# Настройки VK
VK_TOKEN = os.environ.get("VK_GROUP_TOKEN", "")
VK_CONFIRMATION_CODE = os.environ.get("VK_CONFIRMATION_CODE", "e1388965")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask приложение для VK
app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "OK"

@app.route('/vk', methods=['POST'])
def vk_webhook():
    """Обработка запросов от ВКонтакте"""
    try:
        data = request.get_json()
        logger.info(f"VK webhook: {data}")
        
        if data and data.get('type') == 'confirmation':
            return VK_CONFIRMATION_CODE, 200, {'Content-Type': 'text/plain'}
        
        if data and data.get('type') == 'message_new':
            msg = data.get('object', {}).get('message', {})
            user_text = msg.get('text', '')
            peer_id = msg.get('peer_id')
            
            answer = f"✅ Получил: {user_text}\n\nЯ бот-компаньон!"
            
            import requests
            url = 'https://api.vk.com/method/messages.send'
            params = {
                'peer_id': peer_id,
                'message': answer,
                'random_id': 0,
                'access_token': VK_TOKEN,
                'v': '5.199'
            }
            requests.post(url, params=params)
            return "ok", 200
        
        return "ok", 200
    except Exception as e:
        logger.error(f"VK error: {e}")
        return "error", 500

def run_telegram():
    """Запуск Telegram бота с защитой от конфликтов"""
    logger.info("🚀 Запускаем Telegram бота...")
    try:
        # Сначала удаляем вебхук
        import requests
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true")
        
        # Создаём event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем бота
        telegram_app = build_application()
        
        async def start_bot():
            await telegram_app.initialize()
            await telegram_app.start()
            await telegram_app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"]
            )
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                pass
        
        loop.run_until_complete(start_bot())
        
    except Exception as e:
        logger.error(f"Telegram bot error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # Сначала удаляем вебхук при старте
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    try:
        requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true")
        logger.info("✅ Webhook deleted")
    except:
        pass
    
    # Запускаем Telegram бота
    tg_thread = threading.Thread(target=run_telegram, daemon=True)
    tg_thread.start()
    
    # Ждём инициализации
    import time
    time.sleep(3)
    
    # Запускаем Flask для VK
    logger.info(f"🚀 Запускаем VK бота на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
