"""
Сервис практики ОГЭ/ЕГЭ: генерация заданий по формату ФИПИ.

Поддерживает типы заданий:
- ОГЭ: выбор ответа, установление соответствия, работа с датами/событиями
- ЕГЭ: задания с кратким ответом, работа с историческими источниками
"""

import logging

import config
from services import llm_service, rag_service

logger = logging.getLogger(__name__)

# Типы заданий по формату ФИПИ
OGE_TYPES = {
    "date_event": "Установите соответствие между событиями и датами",
    "figure": "Назовите историческую личность по описанию",
    "term": "Дайте определение исторического термина",
    "sequence": "Расположите события в хронологической последовательности",
    "fact": "Выберите верные суждения о событии",
}

EGE_TYPES = {
    "short_answer": "Задание с кратким ответом (дата, имя, термин)",
    "source": "Работа с историческим источником",
    "cause_effect": "Установите причинно-следственные связи",
    "comparison": "Сравните исторические события/явления",
}


def _get_context(topic, max_chars=4000):
    query = topic or "история России для ОГЭ и ЕГЭ"
    chunks = rag_service.retrieve(query, top_k=4)
    return rag_service.build_context(chunks, max_chars=max_chars)


def _normalize_question(result):
    """Нормализует ответ LLM в словарь задания.

    LLM иногда возвращает JSON-массив вместо объекта — берём первый элемент.
    """
    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        return {}
    return result


def generate_oge_question(topic=None, qtype=None):
    """
    Генерирует задание ОГЭ.
    Возвращает dict с вопросом, вариантами и правильным ответом.
    """
    qtype = qtype or "date_event"
    type_desc = OGE_TYPES.get(qtype, OGE_TYPES["date_event"])
    context = _get_context(topic)

    system_prompt = (
        "Ты — составитель заданий ОГЭ по истории по формату ФИПИ. "
        "Составь одно задание на основе контекста. "
        "Верни ТОЛЬКО JSON без пояснений в формате: "
        '{"question": "...", "options": ["...", "...", "...", "..."], '
        '"correct_index": 0, "explanation": "...", "topic": "..."}'
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Тип задания: {type_desc}\n"
                f"КОНТЕКСТ:\n{context}\n\n"
                f"Составь задание по теме: {topic or 'история России'}"
            ),
        },
    ]
    return _normalize_question(llm_service.call_llm(messages, json_mode=True, max_tokens=800))


def generate_ege_question(topic=None, qtype=None):
    """
    Генерирует задание ЕГЭ.
    Возвращает dict с вопросом и правильным ответом.
    """
    qtype = qtype or "short_answer"
    type_desc = EGE_TYPES.get(qtype, EGE_TYPES["short_answer"])
    context = _get_context(topic)

    system_prompt = (
        "Ты — составитель заданий ЕГЭ по истории по формату ФИПИ. "
        "Составь одно задание на основе контекста. "
        "Верни ТОЛЬКО JSON без пояснений в формате: "
        '{"question": "...", "answer": "...", "explanation": "...", "topic": "..."}'
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Тип задания: {type_desc}\n"
                f"КОНТЕКСТ:\n{context}\n\n"
                f"Составь задание по теме: {topic or 'история России'}"
            ),
        },
    ]
    return _normalize_question(llm_service.call_llm(messages, json_mode=True, max_tokens=800))


def check_oge_answer(question, user_answer, correct_index, options):
    """Проверяет ответ на задание ОГЭ.

    Принимает user_answer как номер варианта (1-based), как в Web App и боте.
    """
    try:
        user_idx = int(user_answer) - 1
        correct = user_idx == correct_index
    except (ValueError, TypeError):
        correct = str(user_answer).strip().lower() == str(options[correct_index]).strip().lower()
    return correct


def check_ege_answer(user_answer, correct_answer):
    """Проверяет ответ на задание ЕГЭ (краткий ответ)."""
    return user_answer.strip().lower() == correct_answer.strip().lower()
