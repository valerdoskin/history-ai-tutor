"""
Конфигурация History AI Tutor.
Все настройки читаются из .env (см. .env.example).
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _get_bool(name, default=False):
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _get_int(name, default=0):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ============================================================
# Telegram
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_DOMAIN = os.getenv("WEBHOOK_DOMAIN", "")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# ============================================================
# LLM (DeepSeek — основной, Groq — fallback)
# ============================================================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_URL = os.getenv("DEEPSEEK_URL", "https://api.deepseek.com/chat/completions")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL = os.getenv("GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_MAX_TOKENS = _get_int("LLM_MAX_TOKENS", 2000)

# ============================================================
# Эмбеддинги (локальные multilingual-модели)
# ============================================================
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")

# ============================================================
# Qdrant (векторная БД)
# ============================================================
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "history_tutor")
# Локальный (embedded) режим — если задан путь, используется он
QDRANT_PATH = os.getenv("QDRANT_PATH", "")

# ============================================================
# База данных
# ============================================================
DB_PATH = os.getenv("DB_PATH", "./tutor_bot.db")

# ============================================================
# База знаний
# ============================================================
KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", "./knowledge")
CHUNKS_FILE = os.path.join(KNOWLEDGE_DIR, "chunks.json")
ENRICHED_FILE = os.path.join(KNOWLEDGE_DIR, "enriched.json")

# ============================================================
# RAG
# ============================================================
RAG_TOP_K = _get_int("RAG_TOP_K", 5)
RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.3"))

# ============================================================
# Геймификация
# ============================================================
XP_PER_LESSON = _get_int("XP_PER_LESSON", 20)
XP_PER_QUESTION = _get_int("XP_PER_QUESTION", 10)
XP_STREAK_BONUS = _get_int("XP_STREAK_BONUS", 5)

# ============================================================
# Обогащение (Этап 2)
# ============================================================
ENRICH_MAX_CHARS = _get_int("ENRICH_MAX_CHARS", 6000)
ENRICH_DELAY = float(os.getenv("ENRICH_DELAY", "0.5"))
ENRICH_MAX_RETRIES = _get_int("ENRICH_MAX_RETRIES", 3)

# ============================================================
# Web App
# ============================================================
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = _get_int("WEBAPP_PORT", 8080)
