import os
import json
import requests
from flask import Flask, request

app = Flask(__name__)

CONFIRMATION_CODE = "e1388965"
VK_TOKEN = os.environ.get("VK_GROUP_TOKEN", "")

@app.route('/vk', methods=['POST'])
def vk_webhook():
    # Логируем ВСЁ, что приходит
    print("=" * 50)
    print(f"📨 VK webhook called!")
    print(f"📨 Method: {request.method}")
    print(f"📨 Headers: {dict(request.headers)}")
    print(f"📨 Raw data: {request.get_data(as_text=True)}")
    
    try:
        data = request.get_json()
        print(f"📨 Parsed JSON: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ JSON parsing error: {e}")
        data = None
    
    # Подтверждение сервера
    if data and data.get('type') == 'confirmation':
        print(f"✅ Confirmation request! Sending code: {CONFIRMATION_CODE}")
        return CONFIRMATION_CODE, 200, {'Content-Type': 'text/plain'}
    
    # Новое сообщение
    if data and data.get('type') == 'message_new':
        msg = data.get('object', {}).get('message', {})
        user_text = msg.get('text', '')
        peer_id = msg.get('peer_id')
        user_id = msg.get('from_id')
        
        print(f"💬 NEW MESSAGE RECEIVED!")
        print(f"💬 From user: {user_id}")
        print(f"💬 Peer ID: {peer_id}")
        print(f"💬 Text: {user_text}")
        
        # Отправляем ответ
        answer = f"✅ Бот получил ваше сообщение: '{user_text}'\n\nСпасибо! Я работаю!"
        send_vk_message(peer_id, answer)
        
        print(f"✅ Response sent to VK")
        return "ok", 200
    
    # Если что-то другое
    print(f"⚠️ Unknown event type: {data.get('type') if data else 'no data'}")
    return "ok", 200

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
    
    print(f"📤 Sending VK message to {peer_id}: {text[:50]}...")
    
    try:
        response = requests.post(url, params=params)
        print(f"📤 VK API response status: {response.status_code}")
        print(f"📤 VK API response body: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            if result.get('error'):
                print(f"❌ VK API error: {result['error']}")
            else:
                print(f"✅ Message sent successfully!")
        else:
            print(f"❌ HTTP error: {response.status_code}")
    except Exception as e:
        print(f"❌ Exception while sending: {e}")

@app.route('/')
@app.route('/health')
def health():
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Starting VK bot server on port {port}")
    print(f"📋 Confirmation code: {CONFIRMATION_CODE}")
    print(f"🔑 VK Token set: {'YES' if VK_TOKEN else 'NO'}")
    app.run(host="0.0.0.0", port=port, debug=True)
