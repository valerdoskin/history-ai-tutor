"""
Сервис прогресса: отслеживание изученных тем, XP, streak, статистика.
"""

import logging

import config
from database import db

logger = logging.getLogger(__name__)


def register_user(user_id, username=None, first_name=None):
    """Регистрирует пользователя и возвращает его данные."""
    return db.get_or_create_user(user_id, username, first_name)


def record_activity(user_id):
    """Обновляет streak и last_active при активности пользователя."""
    db.update_streak(user_id)


def add_xp(user_id, amount):
    """Начисляет XP и возвращает новый уровень."""
    return db.add_xp(user_id, amount)


def mark_lesson_complete(user_id, book_id, chapter_number, paragraph_title, score=100):
    """Отмечает параграф изученным."""
    db.update_progress(user_id, book_id, chapter_number, paragraph_title, "completed", score)
    db.add_xp(user_id, config.XP_PER_LESSON)


def get_user_stats(user_id):
    """Возвращает статистику пользователя."""
    return db.get_stats(user_id)


def get_weak_topics(user_id, limit=10):
    """Возвращает слабые темы пользователя."""
    return db.get_weak_topics(user_id, limit)


def get_progress_summary(user_id):
    """Возвращает сводку прогресса."""
    progress = db.get_progress(user_id)
    completed = sum(1 for p in progress if p["status"] == "completed")
    return {
        "total": len(progress),
        "completed": completed,
        "percent": round(completed / len(progress) * 100, 1) if progress else 0,
        "items": progress,
    }
