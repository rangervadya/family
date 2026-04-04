import os
import asyncio
import threading
from flask import Flask
from bot_main import main

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "OK", 200

def run_bot():
    """Запуск бота в фоновом потоке"""
    print("🚀 Запускаем Telegram бота в фоновом потоке...")
    try:
        # Создаем новый event loop для этого потока
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем main в этом потоке
        main()
        
    except Exception as e:
        print(f"❌ Ошибка в боте: {e}")
        import traceback
        traceback.print_exc()

def run_health_server():
    """Запуск Flask сервера для health checks"""
    port = int(os.environ.get("PORT", 10000))
    print(f"🏥 Health check сервер запускается на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    print("=" * 50)
    print("Запуск сервиса...")
    print(f"PORT: {os.environ.get('PORT', '10000')}")
    print("=" * 50)
    
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем health сервер в основном потоке
    run_health_server()
