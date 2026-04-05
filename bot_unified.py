import os
import threading
import logging
from flask import Flask, request

# Импортируем Telegram бота
from bot_main import build_application, main as telegram_main

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
    data = request.get_json()
    logger.info(f"VK webhook: {data}")
    
    # Подтверждение сервера
    if data and data.get('type') == 'confirmation':
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

def run_telegram():
    """Запуск Telegram бота в отдельном потоке"""
    logger.info("🚀 Запускаем Telegram бота...")
    try:
        telegram_main()
    except Exception as e:
        logger.error(f"Telegram bot error: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # Запускаем Telegram бота в фоновом потоке
    tg_thread = threading.Thread(target=run_telegram, daemon=True)
    tg_thread.start()
    
    # Запускаем Flask для VK
    logger.info(f"🚀 Запускаем VK бота на порту {port}")
    app.run(host="0.0.0.0", port=port)
