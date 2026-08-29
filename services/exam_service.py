"""
Сервис практики ОГЭ/ЕГЭ: генерация заданий по формату ФИПИ.

Поддерживает два режима:
1. Генерация из классифицированного реестра вопросов (основной, быстрый):
   вопросы берутся из knowledge/question_types.json, дистракторы — из кэша
   LLM-дистракторов. Не требует обращения к LLM на лету.
2. Генерация через LLM (fallback, медленный): вопросы генерируются
   моделью на основе RAG-контекста.

Типы вопросов реестра и их соответствие заданиям ЕГЭ/ОГЭ:
- fact: знание фактов (ОГЭ 1,4,15,16; ЕГЭ 3,4,5)
- chronology: хронология (ОГЭ 2; ЕГЭ 2)
- cause_effect: причины и следствия (ОГЭ 21; ЕГЭ 18)
- understanding: понимание/объяснение (ОГЭ 19,20; ЕГЭ 14,19)
- comparison: сравнение (ОГЭ 23; ЕГЭ 20)
- term: термины и понятия (ОГЭ 3,5; ЕГЭ 19)
"""

import json
import logging
import os
import random

import config
from services import llm_service, placement_service, rag_service

logger = logging.getLogger(__name__)

# Путь к классифицированным вопросам реестра
_QUESTION_TYPES_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "question_types.json",
)

# Кэш классифицированных вопросов: {вопрос: {class, answer, type}}
_question_types_cache = None

# Типы заданий по формату ФИПИ (для LLM-режима)
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

# Соответствие типов вопросов реестра заданиям ЕГЭ/ОГЭ (по спецификациям ФИПИ)
TYPE_TO_FIPI = {
    "fact": {"label": "Знание фактов", "ege": [3, 4, 5], "oge": [1, 4, 15, 16]},
    "chronology": {"label": "Хронология / последовательность", "ege": [2], "oge": [2]},
    "cause_effect": {"label": "Причины и следствия", "ege": [18], "oge": [21]},
    "understanding": {"label": "Понимание / объяснение", "ege": [14, 19], "oge": [19, 20]},
    "comparison": {"label": "Сравнение", "ege": [20], "oge": [23]},
    "term": {"label": "Термины и понятия", "ege": [19], "oge": [3, 5]},
}


def _load_question_types():
    """Загружает классифицированные вопросы реестра (с кэшем)."""
    global _question_types_cache
    if _question_types_cache is not None:
        return _question_types_cache
    cache = {}
    if os.path.exists(_QUESTION_TYPES_JSON):
        try:
            cache = json.load(open(_QUESTION_TYPES_JSON, encoding="utf-8"))
        except Exception as e:
            logger.error(f"Не удалось загрузить классификацию вопросов: {e}")
    _question_types_cache = cache
    return cache


def get_question_types():
    """Возвращает типы вопросов и их соответствие заданиям ЕГЭ/ОГЭ."""
    return TYPE_TO_FIPI


def _get_context(topic, max_chars=4000, class_filter=None):
    query = topic or "история России для ОГЭ и ЕГЭ"
    chunks = rag_service.retrieve(query, top_k=4, class_filter=class_filter)
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


def _parse_classes(classes):
    """Преобразует фильтр классов в список (или 'all')."""
    if not classes or classes == "all":
        return "all"
    try:
        return [int(x) for x in str(classes).split(",") if x.strip()]
    except (TypeError, ValueError):
        return "all"


def _registry_questions(qtype=None, classes=None):
    """Возвращает список вопросов реестра, отфильтрованных по типу и классам.

    Каждый элемент: {"question", "answer", "class", "type"}.
    """
    data = _load_question_types()
    if not data:
        return []
    classes = _parse_classes(classes)
    result = []
    for question, info in data.items():
        if qtype and info.get("type") != qtype:
            continue
        if classes != "all" and info.get("class") not in classes:
            continue
        result.append({
            "question": question,
            "answer": info.get("answer", ""),
            "class": info.get("class"),
            "type": info.get("type"),
        })
    return result


def _build_mcq(question, answer, distractors):
    """Собирает MCQ: правильный ответ + дистракторы, перемешивает."""
    options = [answer] + distractors[:3]
    random.shuffle(options)
    correct_index = options.index(answer)
    return {
        "question": question,
        "options": options,
        "correct_index": correct_index,
        "explanation": "",
        "topic": "",
    }


def generate_oge_question_from_registry(qtype=None, classes=None):
    """Генерирует задание ОГЭ из классифицированного реестра.

    Возвращает MCQ с 4 вариантами (правильный + 3 дистрактора из кэша).
    Если реестр пуст — возвращает None.
    """
    questions = _registry_questions(qtype=qtype, classes=classes)
    if not questions:
        return None
    q = random.choice(questions)
    distractors = placement_service._llm_distractors(q["question"], q["answer"], n=3)
    if distractors is None:
        distractors = placement_service._semantic_distractors(q["question"], q["class"], n=3)
    if distractors is None:
        distractors = placement_service._fallback_distractors(
            {"question": q["question"], "answer": q["answer"], "paragraph": ""},
            q["class"],
            classes if classes != "all" else placement_service.ALL_CLASSES,
            n=3,
        )
    mcq = _build_mcq(q["question"], q["answer"], distractors)
    mcq["type"] = q["type"]
    mcq["class"] = q["class"]
    mcq["fipi_numbers"] = TYPE_TO_FIPI.get(q["type"], {}).get("oge", [])
    return mcq


def generate_ege_question_from_registry(qtype=None, classes=None):
    """Генерирует задание ЕГЭ из классифицированного реестра.

    Возвращает задание с кратким ответом (вопрос + ответ).
    Если реестр пуст — возвращает None.
    """
    questions = _registry_questions(qtype=qtype, classes=classes)
    if not questions:
        return None
    q = random.choice(questions)
    return {
        "question": q["question"],
        "answer": q["answer"],
        "explanation": "",
        "topic": "",
        "type": q["type"],
        "class": q["class"],
        "fipi_numbers": TYPE_TO_FIPI.get(q["type"], {}).get("ege", []),
    }


def generate_oge_question(topic=None, qtype=None, classes=None):
    """
    Генерирует задание ОГЭ.

    Сначала пробует взять вопрос из классифицированного реестра (быстро,
    без LLM). Если реестр пуст — генерирует через LLM.

    Возвращает dict с вопросом, вариантами и правильным ответом.
    """
    from_registry = generate_oge_question_from_registry(qtype=qtype, classes=classes)
    if from_registry:
        return from_registry

    qtype = qtype or "date_event"
    type_desc = OGE_TYPES.get(qtype, OGE_TYPES["date_event"])
    context = _get_context(topic, class_filter=classes)

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


def generate_ege_question(topic=None, qtype=None, classes=None):
    """
    Генерирует задание ЕГЭ.

    Сначала пробует взять вопрос из классифицированного реестра (быстро,
    без LLM). Если реестр пуст — генерирует через LLM.

    Возвращает dict с вопросом и правильным ответом.
    """
    from_registry = generate_ege_question_from_registry(qtype=qtype, classes=classes)
    if from_registry:
        return from_registry

    qtype = qtype or "short_answer"
    type_desc = EGE_TYPES.get(qtype, EGE_TYPES["short_answer"])
    context = _get_context(topic, class_filter=classes)

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
