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
    """Запуск бота с игнорированием ошибок сигналов"""
    print("🚀 Запускаем Telegram бота...")
    try:
        # Создаем отдельный event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Отключаем обработку сигналов в этом потоке
        import signal
        original_handlers = {}
        for sig in [signal.SIGINT, signal.SIGTERM, signal.SIGABRT]:
            original_handlers[sig] = signal.signal(sig, signal.SIG_IGN)
        
        try:
            main()
        finally:
            # Восстанавливаем обработчики
            for sig, handler in original_handlers.items():
                signal.signal(sig, handler)
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🏥 Health check сервер на порту {port}")
    
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask
    app.run(host="0.0.0.0", port=port, debug=False)
