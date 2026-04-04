import os
import asyncio
import threading
import warnings
from flask import Flask

# Игнорируем предупреждения
warnings.filterwarnings("ignore")

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "OK", 200

def run_bot():
    """Запуск бота в отдельном потоке"""
    print("🚀 Запускаем Telegram бота...")
    try:
        # Импортируем main здесь, чтобы избежать проблем с event loop
        from bot_main import main
        
        # Создаем новый event loop для этого потока
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Запускаем бота
        main()
        
    except Exception as e:
        print(f"❌ Ошибка бота: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🏥 Health check сервер на порту {port}")
    
    # Запускаем бота в потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Даем боту время на инициализацию
    import time
    time.sleep(2)
    
    # Запускаем Flask
    app.run(host="0.0.0.0", port=port, debug=False)
