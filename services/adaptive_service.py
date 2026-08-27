"""
Сервис адаптивного обучения: определение уровня, персонализация.

Определяет уровень знаний пользователя и подбирает задания
сложности, соответствующей его прогрессу.
"""

import logging

from database import db

logger = logging.getLogger(__name__)


def estimate_level(user_id):
    """
    Оценивает уровень знаний пользователя (1-5).
    На основе точности ответов и количества изученных тем.
    """
    stats = db.get_stats(user_id)
    accuracy = stats["accuracy"]
    total_q = stats["total_questions"]
    progress_count = len(db.get_progress(user_id))

    if total_q == 0:
        return 1  # новичок

    # Базовая оценка по точности
    if accuracy >= 90:
        base = 5
    elif accuracy >= 75:
        base = 4
    elif accuracy >= 60:
        base = 3
    elif accuracy >= 40:
        base = 2
    else:
        base = 1

    # Корректировка по количеству вопросов и изученных тем
    if total_q < 5:
        base = min(base, 2)
    if progress_count < 3:
        base = min(base, 2)

    return max(1, min(5, base))


def get_difficulty(user_id):
    """Возвращает рекомендуемую сложность заданий."""
    level = estimate_level(user_id)
    if level <= 2:
        return "easy"
    if level <= 4:
        return "medium"
    return "hard"


def get_recommended_topics(user_id, limit=5):
    """Возвращает темы для повторения (слабые места)."""
    return db.get_weak_topics(user_id, limit)


def personalize_prompt(user_id):
    """
    Возвращает персональную инструкцию для LLM на основе уровня пользователя.
    """
    level = estimate_level(user_id)
    weak = db.get_weak_topics(user_id, 3)
    weak_str = ", ".join(t["topic"] for t in weak) if weak else "нет"

    prompts = {
        1: "Объясняй простым языком, с примерами. Избегай сложных терминов.",
        2: "Объясняй понятно, добавляй ключевые даты и имена.",
        3: "Объясняй подробно, с причинно-следственными связями.",
        4: "Объясняй глубоко, с анализом и сравнением событий.",
        5: "Объясняй на высоком уровне, с историографией и дискуссиями.",
    }
    return (
        f"Уровень ученика: {level}/5. "
        f"{prompts.get(level, prompts[3])} "
        f"Слабые темы для повторения: {weak_str}."
    )
