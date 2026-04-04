import os
import threading
from flask import Flask
from bot_main import main  # предполагаю, что ваш бот запускается через main()

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=main, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask сервер для health checks
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
