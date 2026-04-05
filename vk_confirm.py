import os
import json
import requests
from flask import Flask, request

app = Flask(__name__)

CONFIRMATION_CODE = "e1388965"
VK_TOKEN = os.environ.get("VK_GROUP_TOKEN", "")

@app.route('/vk', methods=['POST'])
def vk_webhook():
    print("=" * 50)
    print(f"📨 VK webhook called!")
    
    try:
        data = request.get_json()
        print(f"📨 Received: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ JSON parsing error: {e}")
        data = None
    
    # Подтверждение сервера
    if data and data.get('type') == 'confirmation':
        print(f"✅ Confirmation! Sending code: {CONFIRMATION_CODE}")
        return CONFIRMATION_CODE, 200, {'Content-Type': 'text/plain'}
    
    # Новое сообщение
    if data and data.get('type') == 'message_new':
        msg = data.get('object', {}).get('message', {})
        user_text = msg.get('text', '').strip()
        peer_id = msg.get('peer_id')
        
        print(f"💬 New message: '{user_text}' from {peer_id}")
        
        # Логика ответа
        answer = generate_response(user_text)
        
        # Отправляем ответ
        send_vk_message(peer_id, answer)
        
        return "ok", 200
    
    return "ok", 200

def generate_response(text):
    """Генерация ответа бота"""
    text_lower = text.lower()
    
    # Команда /start или приветствие
    if text_lower in ['/start', 'начать', 'start', 'привет', 'здравствуй']:
        return (
            "🌷 Здравствуйте! Я бот-компаньон «Семья».\n\n"
            "Я помогу вам:\n"
            "• 💬 Поддержать разговор\n"
            "• 📅 Напомнить о важном\n"
            "• 👥 Рассказать о событиях\n"
            "• 🆘 Отправить сигнал SOS близким\n\n"
            "Просто напишите мне любое сообщение!"
        )
    
    # Вопрос о погоде
    if 'погод' in text_lower:
        return (
            "🌤️ Погода сегодня отличная!\n\n"
            "Скоро я научусь показывать точный прогноз для вашего города. "
            "А пока желаю хорошего дня!"
        )
    
    # Вопрос о том, как дела
    if any(word in text_lower for word in ['как дела', 'как ты', 'дела как']):
        return (
            "У меня всё отлично! 🌷\n\n"
            "Я учусь новому каждый день, чтобы лучше помогать вам. "
            "А как ваши дела?"
        )
    
    # Стандартный ответ
    return (
        f"✅ Я получил ваше сообщение: '{text}'\n\n"
        "Я бот-компаньон «Семья». Скоро я научусь:\n"
        "• 📝 Запоминать важные даты\n"
        "• 💊 Напоминать о лекарствах\n"
        "• 👨‍👩‍👧 Связывать с родственниками\n\n"
        "А пока просто поболтаем! 😊"
    )

def send_vk_message(peer_id, text):
    """Отправка сообщения через API VK"""
    url = "https://api.vk.com/method/messages.send"
    params = {
        "peer_id": peer_id,
        "message": text,
        "random_id": 0,
        "access_token": VK_TOKEN,
        "v": "5.199"
    }
    
    try:
        response = requests.post(url, params=params)
        if response.status_code == 200:
            result = response.json()
            if result.get('error'):
                print(f"❌ VK API error: {result['error']}")
            else:
                print(f"✅ Message sent to {peer_id}")
        else:
            print(f"❌ HTTP error: {response.status_code}")
    except Exception as e:
        print(f"❌ Exception: {e}")

@app.route('/')
@app.route('/health')
def health():
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Starting VK bot on port {port}")
    app.run(host="0.0.0.0", port=port)
