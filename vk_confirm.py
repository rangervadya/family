import os
from flask import Flask, request

app = Flask(__name__)

# Код подтверждения из VK (ваш новый код)
CONFIRMATION_CODE = "e1388965"

@app.route('/vk', methods=['POST'])
def vk_webhook():
    data = request.get_json()
    print(f"Received: {data}")
    
    # Если это запрос подтверждения
    if data and data.get('type') == 'confirmation':
        return CONFIRMATION_CODE, 200, {'Content-Type': 'text/plain'}
    
    return "ok", 200

@app.route('/')
@app.route('/health')
def health():
    return "OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
