"""
Прокси для Web App.

Используется для локальной разработки, когда Web App должен быть
доступен по HTTPS (требование Telegram). Проксирует запросы
на локальный Flask-сервер.
"""

import logging
import os

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    if not config.WEBAPP_DOMAIN:
        logger.error("WEBAPP_DOMAIN не задан в .env")
        return

    # В продакшене (Render) используется index.py напрямую.
    # Этот скрипт — для локальной разработки с ngrok/cloudflared.
    from bot_webhook import app

    logger.info(f"Запуск Web App на {config.WEBAPP_HOST}:{config.WEBAPP_PORT}")
    app.run(host=config.WEBAPP_HOST, port=config.WEBAPP_PORT)


if __name__ == "__main__":
    main()
