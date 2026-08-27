"""
WSGI entry point для деплоя (Render, PythonAnywhere и т.д.).
"""

from bot_webhook import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
