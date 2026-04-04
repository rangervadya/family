import os
import threading
import time
from flask import Flask

# Импортируйте вашу функцию main из bot_main.py
# Если функция называется по-другому, исправьте
try:
    from bot_main import main
except ImportError:
    print("❌ Не удалось импортировать main из bot_main.py")
    print("Проверьте, что файл bot_main.py существует и функция называется main()")
    raise

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "OK", 200

@app.route('/ping')
def ping():
    return "pong", 200

def run_bot():
    """Запуск бота в отдельном потоке"""
    print("🚀 Запускаем Telegram бота в фоновом потоке...")
    try:
        main()
    except Exception as e:
        print(f"❌ Ошибка в боте: {e}")

def run_health_server():
    """Запуск Flask сервера для health checks"""
    port = int(os.environ.get("PORT", 5000))
    print(f"🏥 Health check сервер запускается на порту {port}")
    print(f"🌐 Проверьте: http://localhost:{port}/health")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    print("=" * 50)
    print("Запуск сервиса...")
    print(f"Python version: {os.sys.version}")
    print(f"PORT: {os.environ.get('PORT', '5000 (default)')}")
    print("=" * 50)
    
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Даем боту немного времени на инициализацию
    time.sleep(2)
    
    # Запускаем health сервер в основном потоке
    run_health_server()
