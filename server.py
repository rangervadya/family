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
    """Запуск бота в фоновом потоке без signal handlers"""
    print("🚀 Запускаем Telegram бота в фоновом потоке...")
    try:
        # Создаем новый event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Используем run_polling с отключенными signal handlers
        # Для этого нужно модифицировать вызов main()
        # Временно переопределяем функцию
        from telegram.ext import Application
        
        # Получаем существующий application из вашего bot_main
        # Если у вас нет доступа к application, нужно импортировать
        import bot_main
        app_instance = bot_main.application  # предположим, что он там есть
        
        # Запускаем polling без signal handlers
        async def start():
            await app_instance.run_polling(
                drop_pending_updates=True,
                signal_handlers=False  # КЛЮЧЕВОЙ ПАРАМЕТР
            )
        
        loop.run_until_complete(start())
        
    except Exception as e:
        print(f"❌ Ошибка в боте: {e}")
        import traceback
        traceback.print_exc()

def run_health_server():
    """Запуск Flask сервера"""
    port = int(os.environ.get("PORT", 10000))
    print(f"🏥 Health check сервер на порту {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    print("=" * 50)
    print("Запуск сервиса...")
    print(f"PORT: {os.environ.get('PORT', '10000')}")
    print("=" * 50)
    
    # Запускаем бота в потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Health сервер в основном потоке
    run_health_server()
