"""
Сервис геймификации: XP, уровни, ранги, достижения, streak.
"""

import logging

import config
from database import db

logger = logging.getLogger(__name__)

# Ранги по уровню
RANKS = [
    (1, "Новичок"),
    (3, "Ученик"),
    (5, "Знаток"),
    (8, "Эксперт"),
    (12, "Мастер истории"),
    (16, "Легенда"),
]

# Достижения
ACHIEVEMENTS = {
    "first_lesson": {"title": "Первый шаг", "desc": "Изучил первый параграф", "xp": 10},
    "streak_3": {"title": "Три дня подряд", "desc": "Занимался 3 дня подряд", "xp": 20},
    "streak_7": {"title": "Неделя практики", "desc": "Занимался 7 дней подряд", "xp": 50},
    "lessons_10": {"title": "Десять параграфов", "desc": "Изучил 10 параграфов", "xp": 30},
    "lessons_50": {"title": "Половина пути", "desc": "Изучил 50 параграфов", "xp": 100},
    "quiz_10": {"title": "Десять вопросов", "desc": "Ответил на 10 вопросов", "xp": 30},
    "quiz_perfect": {"title": "Без ошибок", "desc": "Ответил на 10 вопросов подряд без ошибок", "xp": 50},
    "exam_oge": {"title": "Готов к ОГЭ", "desc": "Решил 20 заданий ОГЭ", "xp": 80},
    "exam_ege": {"title": "Готов к ЕГЭ", "desc": "Решил 20 заданий ЕГЭ", "xp": 100},
}


def get_rank(level):
    """Возвращает ранг по уровню."""
    rank = RANKS[0][1]
    for lvl, name in RANKS:
        if level >= lvl:
            rank = name
    return rank


def award_xp(user_id, amount):
    """Начисляет XP, обновляет уровень и ранг."""
    new_level = db.add_xp(user_id, amount)
    if new_level:
        rank = get_rank(new_level)
        db.update_user(user_id, level=new_level, rank=rank)
    return new_level


def check_achievements(user_id):
    """
    Проверяет и разблокирует достижения.
    Возвращает список новых достижений.
    """
    stats = db.get_stats(user_id)
    user = stats["user"]
    unlocked = set(db.get_achievements(user_id))
    new_achievements = []

    # Проверяем условия
    conditions = {
        "first_lesson": stats["total_questions"] > 0 or len(db.get_progress(user_id)) > 0,
        "streak_3": (user or {}).get("streak", 0) >= 3,
        "streak_7": (user or {}).get("streak", 0) >= 7,
        "lessons_10": len(db.get_progress(user_id)) >= 10,
        "lessons_50": len(db.get_progress(user_id)) >= 50,
        "quiz_10": stats["total_questions"] >= 10,
        "exam_oge": stats["total_questions"] >= 20,
        "exam_ege": stats["total_questions"] >= 20,
    }

    for ach_id, cond in conditions.items():
        if cond and ach_id not in unlocked:
            db.unlock_achievement(user_id, ach_id)
            db.add_xp(user_id, ACHIEVEMENTS[ach_id]["xp"])
            new_achievements.append(ACHIEVEMENTS[ach_id])

    return new_achievements


def get_profile(user_id):
    """Возвращает профиль пользователя для отображения."""
    stats = db.get_stats(user_id)
    user = stats["user"]
    achievements = db.get_achievements(user_id)
    return {
        "user": user,
        "stats": stats,
        "achievements": [ACHIEVEMENTS.get(a, {"title": a}) for a in achievements],
        "rank": user.get("rank") if user else "Новичок",
    }
