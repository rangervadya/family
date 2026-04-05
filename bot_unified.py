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

@app.route('/telegram_webhook', methods=['POST'])
def telegram_webhook():
    """Заглушка для Telegram webhook (используем polling, не webhook)"""
    return "OK", 200

@app.route('/vk', methods=['POST'])
def vk_webhook():
    """Обработка запросов от ВКонтакте"""
    try:
        data = request.get_json()
        logger.info(f"VK webhook: {data}")
        
        # Подтверждение сервера
        if data and data.get('type') == 'confirmation':
            logger.info(f"Sending confirmation: {VK_CONFIRMATION_CODE}")
            return VK_CONFIRMATION_CODE, 200, {'Content-Type': 'text/plain'}
        
        # Новое сообщение
        if data and data.get('type') == 'message_new':
            msg = data.get('object', {}).get('message', {})
            user_text = msg.get('text', '')
            peer_id = msg.get('peer_id')
            
            logger.info(f"VK message from {peer_id}: {user_text}")
            
            # Простой ответ
            answer = f"✅ Получил: {user_text}\n\nЯ бот-компаньон «Семья»!"
            
            # Отправляем ответ через API VK
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
        logger.error(f"VK webhook error: {e}")
        return "error", 500

def run_telegram():
    """Запуск Telegram бота в отдельном потоке с event loop"""
    logger.info("🚀 Запускаем Telegram бота...")
    try:
        # Создаём новый event loop для этого потока
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Создаём приложение Telegram
        telegram_app = build_application()
        
        # Запускаем polling с правильным event loop
        async def start_bot():
            await telegram_app.initialize()
            await telegram_app.start()
            await telegram_app.updater.start_polling(drop_pending_updates=True)
            # Держим бота запущенным
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                pass
            finally:
                await telegram_app.updater.stop()
                await telegram_app.shutdown()
        
        # Запускаем асинхронную функцию
        loop.run_until_complete(start_bot())
        
    except Exception as e:
        logger.error(f"Telegram bot error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # Запускаем Telegram бота в фоновом потоке
    tg_thread = threading.Thread(target=run_telegram, daemon=True)
    tg_thread.start()
    
    # Даём боту время на инициализацию
    import time
    time.sleep(2)
    
    # Запускаем Flask для VK
    logger.info(f"🚀 Запускаем VK бота на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
