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
    """Запуск бота с правильным event loop"""
    print("🚀 Запускаем Telegram бота в фоновом потоке...")
    try:
        # Создаем новый event loop для этого потока
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Если main - синхронная функция
        main()
        
        # ИЛИ если main - асинхронная, используйте:
        # loop.run_until_complete(main())
        
        loop.run_forever()
    except Exception as e:
        print(f"❌ Ошибка в боте: {e}")
        import traceback
        traceback.print_exc()

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
    print(f"PORT: {os.environ.get('PORT', '10000 (default)')}")
    print("=" * 50)
    
    # Запускаем бота в отдельном потоке с правильным event loop
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем health сервер в основном потоке
    run_health_server()
