"""
Сервис аналитики: статистика обучения, слабые места, рекомендации.
"""

import logging

from database import db

logger = logging.getLogger(__name__)


def get_learning_report(user_id):
    """
    Формирует отчёт об обучении пользователя.
    Возвращает dict с общей статистикой и слабыми темами.
    """
    stats = db.get_stats(user_id)
    weak_topics = db.get_weak_topics(user_id)
    progress = db.get_progress(user_id)

    return {
        "stats": stats,
        "weak_topics": weak_topics,
        "progress_count": len(progress),
        "recommendations": _build_recommendations(weak_topics),
    }


def _build_recommendations(weak_topics):
    """Строит рекомендации на основе слабых тем."""
    recommendations = []
    for topic in weak_topics[:5]:
        recommendations.append(
            f"Повторите тему: {topic['topic']} (ошибок: {topic['error_count']})"
        )
    if not recommendations:
        recommendations.append("Отличная работа! Продолжайте в том же духе.")
    return recommendations
