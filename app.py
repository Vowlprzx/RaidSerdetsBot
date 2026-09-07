import os
import threading
import time
from flask import Flask
from main import bot, dp  # Предполагается, что в main.py у тебя есть bot и dp

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/health')
def health():
    return "OK"

# Функция для запуска бота в отдельном потоке
def run_bot():
    import asyncio
    from main import main
    asyncio.run(main())

if __name__ == '__main__':
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Запускаем Flask-сервер, который будет слушать порт Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)