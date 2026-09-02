"""
Сервис адаптивного обучения: определение уровня, персонализация,
интервальное повторение (SRS) и ежедневные карточки.

Определяет уровень знаний пользователя, подбирает задания
сложности, соответствующей его прогрессу, и организует
повторение материала по алгоритму SM-2.
"""

import logging

from database import db

logger = logging.getLogger(__name__)

# Порог качества для SM-2 (ниже — карточка считается забытой)
SRS_PASS_THRESHOLD = 3

# Соответствие типа задания навыку/теме для отслеживания слабых мест.
# Культура, карты, источники и аргументация выделены в отдельные навыки,
# чтобы ошибки в них фиксировались как самостоятельные слабые темы.
SKILL_TOPICS = {
    "culture": "Культура",
    "map": "Карты",
    "source": "Источники",
    "argumentation": "Аргументация",
    "fact": "Факты и даты",
    "chronology": "Хронология",
    "cause_effect": "Причинно-следственные связи",
    "understanding": "Понимание и анализ",
    "comparison": "Сравнение",
    "term": "Термины и понятия",
}


def topic_for_question(question):
    """Определяет тему/навык вопроса для отслеживания слабых мест.

    Приоритет — явное поле topic (например, «Культура» у вопросов из
    culture.json). Если его нет — выводим тему из типа задания.
    """
    topic = (question or {}).get("topic") or ""
    if topic:
        return topic
    qtype = (question or {}).get("type") or ""
    return SKILL_TOPICS.get(qtype, "")


def record_answer(user_id, exam_type, question, user_answer, correct_answer, is_correct):
    """Записывает результат ответа и обновляет слабые темы.

    Тема определяется по вопросу (поле topic или тип задания). Если ученик
    ошибся в вопросе культуры — «Культура» фиксируется как слабая тема.
    """
    topic = topic_for_question(question)
    db.add_exam_result(
        user_id,
        exam_type,
        (question or {}).get("question", ""),
        user_answer,
        correct_answer,
        int(is_correct),
        topic,
    )


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


# ============================================================
# SRS (интервальное повторение) и ежедневные карточки
# ============================================================
def add_card(user_id, topic, question, answer):
    """Добавляет карточку для интервального повторения."""
    db.add_srs_card(user_id, topic, question, answer)
    return {"status": "ok", "topic": topic}


def get_daily_cards(user_id, limit=10):
    """
    Возвращает ежедневные карточки для повторения.
    Сначала — карточки, подлежащие повторению (due), затем новые из слабых тем.
    """
    due = db.get_due_cards(user_id, limit)
    if len(due) >= limit:
        return due

    # Добираем карточки из слабых тем, если их ещё нет в SRS
    existing_topics = {c["topic"] for c in db.get_all_cards(user_id)}
    weak = db.get_weak_topics(user_id, limit=5)
    for topic in weak:
        if len(due) >= limit:
            break
        if topic["topic"] in existing_topics:
            continue
        card = _make_card_from_topic(user_id, topic["topic"])
        if card:
            due.append(card)
    return due


def _make_card_from_topic(user_id, topic):
    """Создаёт карточку-вопрос по слабой теме (без вызова LLM)."""
    question = f"Повтори тему: {topic}"
    answer = "Открой раздел «Темы» и прочитай материал по этой теме."
    db.add_srs_card(user_id, topic, question, answer)
    cards = db.get_all_cards(user_id, limit=1)
    return cards[0] if cards else None


def review_card(card_id, quality):
    """
    Оценивает карточку по шкале 0-5 (SM-2).
    Возвращает обновлённую карточку и следующий интервал повторения.
    """
    card = db.review_srs_card(card_id, quality)
    if not card:
        return None
    return {
        "card": card,
        "passed": quality >= SRS_PASS_THRESHOLD,
        "next_interval_days": card["interval"],
    }


def get_srs_summary(user_id):
    """Возвращает сводку по карточкам пользователя."""
    all_cards = db.get_all_cards(user_id)
    due_count = db.count_due_cards(user_id)
    return {
        "total_cards": len(all_cards),
        "due_cards": due_count,
        "learned_cards": sum(1 for c in all_cards if c["repetitions"] >= 3),
    }
