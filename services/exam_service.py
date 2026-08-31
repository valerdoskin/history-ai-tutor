"""
Сервис практики ОГЭ/ЕГЭ: генерация заданий по формату ФИПИ.

Поддерживает два режима:
1. Генерация из банка вопросов (основной, быстрый):
   вопросы и дистракторы берутся из knowledge/question_bank.json.
   Не требует обращения к LLM на лету.
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

# Путь к банку вопросов
_QUESTION_BANK_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "question_bank.json",
)

# Кэш банка вопросов: {вопрос: {class, answer, type, distractors}}
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
    """Загружает банк вопросов (с кэшем)."""
    global _question_types_cache
    if _question_types_cache is not None:
        return _question_types_cache
    cache = {}
    if os.path.exists(_QUESTION_BANK_JSON):
        try:
            cache = json.load(open(_QUESTION_BANK_JSON, encoding="utf-8"))
        except Exception as e:
            logger.error(f"Не удалось загрузить банк вопросов: {e}")
    _question_types_cache = cache
    return cache


def get_question_types():
    """Возвращает типы вопросов и их соответствие заданиям ЕГЭ/ОГЭ."""
    return TYPE_TO_FIPI


# Маппинг типов LLM-режима на типы банка вопросов
_LLM_TO_BANK_TYPE = {
    # ОГЭ
    "date_event": "chronology",
    "figure": "fact",
    "sequence": "chronology",
    # ЕГЭ
    "short_answer": "fact",
    "source": "understanding",
}


def _normalize_bank_type(qtype):
    """Приводит тип вопроса к типу банка (fact/chronology/cause_effect/...).

    Если тип уже банковский — возвращает как есть, иначе сопоставляет
    через _LLM_TO_BANK_TYPE, иначе — fact.
    """
    if qtype in TYPE_TO_FIPI:
        return qtype
    return _LLM_TO_BANK_TYPE.get(qtype, "fact")


def _save_question_to_bank(question, answer, distractors, qtype, classes):
    """Сохраняет сгенерированный LLM вопрос в банк (кэш + диск).

    Вопрос сохраняется только если его ещё нет в банке. Дистракторы
    добавляются, если их не хватает. Возвращает True при успехе.
    """
    if not question or not answer:
        return False
    bank = _load_question_types()
    bank_type = _normalize_bank_type(qtype)
    entry = bank.get(question)
    if isinstance(entry, dict):
        # Вопрос уже есть — дополняем недостающие поля
        if not entry.get("answer"):
            entry["answer"] = answer
        if not entry.get("type"):
            entry["type"] = bank_type
        if not entry.get("class"):
            entry["class"] = classes if classes != "all" else None
        existing = entry.get("distractors", [])
        for d in distractors:
            if d and d != answer and d not in existing:
                existing.append(d)
        entry["distractors"] = existing[:3]
    else:
        bank[question] = {
            "class": classes if classes != "all" else None,
            "answer": answer,
            "type": bank_type,
            "distractors": [d for d in distractors if d and d != answer][:3],
        }
    try:
        with open(_QUESTION_BANK_JSON, "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Не удалось сохранить вопрос в банк: {e}")
        return False


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
    """Возвращает список вопросов банка, отфильтрованных по типу и классам.

    Каждый элемент: {"question", "answer", "class", "type", "distractors"}.
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
            "distractors": info.get("distractors", []),
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
    distractors = q.get("distractors") or []
    if len(distractors) < 3:
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
    result = _normalize_question(llm_service.call_llm(messages, json_mode=True, max_tokens=800))
    # Сохраняем сгенерированный вопрос в банк для переиспользования
    if result.get("question") and result.get("options") and result.get("correct_index") is not None:
        try:
            options = result["options"]
            correct_index = int(result["correct_index"])
            if 0 <= correct_index < len(options):
                answer = options[correct_index]
                distractors = [o for i, o in enumerate(options) if i != correct_index]
                _save_question_to_bank(
                    result["question"], answer, distractors, qtype, classes
                )
        except (ValueError, TypeError):
            pass
    return result


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
    result = _normalize_question(llm_service.call_llm(messages, json_mode=True, max_tokens=800))
    # Сохраняем сгенерированный вопрос в банк для переиспользования
    if result.get("question") and result.get("answer"):
        _save_question_to_bank(
            result["question"], result["answer"], [], qtype, classes
        )
    return result


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


# ============================================================
# Полноценный тест (10 заданий) по формату ФИПИ
# ============================================================

# Путь к реестру вопросов по источникам
_SOURCE_QUESTIONS_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "source_questions.json",
)

# Кэш реестра вопросов по источникам
_source_questions_cache = None

# Баллы ФИПИ для типов заданий (по спецификациям ЕГЭ/ОГЭ)
FIPI_POINTS = {
    "mcq": 1,          # выбор ответа (ОГЭ 1-17)
    "short": 2,        # краткий ответ (ЕГЭ 3-6)
    "source": 3,       # развёрнутый ответ по источнику (ЕГЭ 17-21)
    "open": 3,         # развёрнутый ответ (ЕГЭ 20-21)
}

# Структура полноценного теста: 10 заданий
# (гибрид ЕГЭ/ОГЭ: MCQ, краткий ответ, развёрнутый ответ по источнику)
TEST_STRUCTURE = [
    {"type": "mcq", "count": 4, "points": FIPI_POINTS["mcq"]},
    {"type": "short", "count": 4, "points": FIPI_POINTS["short"]},
    {"type": "source", "count": 2, "points": FIPI_POINTS["source"]},
]


def _load_source_questions():
    """Загружает реестр вопросов по источникам (с кэшем).

    Возвращает список dict: {"source_text", "source_title", "class",
    "source_file", "questions": [{"question", "answer", "type"}]}.
    """
    global _source_questions_cache
    if _source_questions_cache is not None:
        return _source_questions_cache
    cache = []
    if os.path.exists(_SOURCE_QUESTIONS_JSON):
        try:
            data = json.load(open(_SOURCE_QUESTIONS_JSON, encoding="utf-8"))
            for key, info in data.items():
                cache.append({
                    "source_text": info.get("source_text", ""),
                    "source_title": info.get("source_title", ""),
                    "class": info.get("class"),
                    "source_file": info.get("source_file", ""),
                    "questions": info.get("questions", []),
                })
        except Exception as e:
            logger.error(f"Не удалось загрузить реестр вопросов по источникам: {e}")
    _source_questions_cache = cache
    return cache


def _source_questions_for_class(classes):
    """Возвращает вопросы по источникам, отфильтрованные по классам."""
    sources = _load_source_questions()
    classes = _parse_classes(classes)
    result = []
    for src in sources:
        if classes != "all" and src.get("class") not in classes:
            continue
        for q in src.get("questions", []):
            result.append({
                "question": q.get("question", ""),
                "answer": q.get("answer", ""),
                "type": "source",
                "class": src.get("class"),
                "source_text": src.get("source_text", ""),
                "source_title": src.get("source_title", ""),
            })
    return result


def _build_source_task(classes):
    """Собирает задание по источнику (гибрид: реестр + база знаний).

    Берёт вопрос из реестра source_questions.json. Если реестр пуст —
    извлекает источник из базы знаний и генерирует вопрос через LLM.
    """
    questions = _source_questions_for_class(classes)
    if questions:
        q = random.choice(questions)
        return {
            "type": "source",
            "question": q["question"],
            "answer": q["answer"],
            "points": FIPI_POINTS["source"],
            "class": q["class"],
            "source_text": q["source_text"],
            "source_title": q["source_title"],
            "fipi_numbers": [17, 18, 19, 20, 21],
        }
    # Fallback: извлечь источник из базы знаний и сгенерировать вопрос через LLM
    return _generate_source_task_llm(classes)


def _generate_source_task_llm(classes):
    """Генерирует задание по источнику через LLM (fallback)."""
    try:
        context = _get_context("исторический источник", class_filter=classes)
        system_prompt = (
            "Ты — составитель заданий ЕГЭ по истории по формату ФИПИ. "
            "Составь задание на работу с историческим источником на основе контекста. "
            "Верни ТОЛЬКО JSON без пояснений в формате: "
            '{"question": "...", "answer": "...", "source_text": "...", "source_title": "..."}'
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"КОНТЕКСТ:\n{context}\n\nСоставь задание по источнику."},
        ]
        result = _normalize_question(llm_service.call_llm(messages, json_mode=True, max_tokens=800))
        if result.get("question") and result.get("answer"):
            return {
                "type": "source",
                "question": result["question"],
                "answer": result["answer"],
                "points": FIPI_POINTS["source"],
                "class": None,
                "source_text": result.get("source_text", ""),
                "source_title": result.get("source_title", ""),
                "fipi_numbers": [17, 18, 19, 20, 21],
            }
    except Exception as e:
        logger.error(f"Ошибка генерации задания по источнику: {e}")
    return None


def generate_full_test(classes=None):
    """Генерирует полноценный тест из 10 заданий по формату ФИПИ.

    Смесь типов: MCQ (выбор ответа), краткий ответ, развёрнутый ответ
    по источнику. Каждое задание имеет балл по спецификации ФИПИ.

    Возвращает dict: {"test_id", "questions": [...], "total_points"}.
    """
    classes = _parse_classes(classes)
    questions = []

    # MCQ (выбор ответа) — из банка вопросов question_bank.json
    mcq_types = ["fact", "chronology", "cause_effect", "understanding", "comparison", "term"]
    for _ in range(TEST_STRUCTURE[0]["count"]):
        qtype = random.choice(mcq_types)
        mcq = generate_oge_question_from_registry(qtype=qtype, classes=classes)
        if mcq:
            mcq["type"] = "mcq"
            mcq["points"] = TEST_STRUCTURE[0]["points"]
            questions.append(mcq)

    # Краткий ответ — из банка вопросов question_bank.json
    for _ in range(TEST_STRUCTURE[1]["count"]):
        qtype = random.choice(mcq_types)
        short = generate_ege_question_from_registry(qtype=qtype, classes=classes)
        if short:
            short["type"] = "short"
            short["points"] = TEST_STRUCTURE[1]["points"]
            questions.append(short)

    # Развёрнутый ответ по источнику — из реестра source_questions.json
    for _ in range(TEST_STRUCTURE[2]["count"]):
        src = _build_source_task(classes)
        if src:
            questions.append(src)

    # Если каких-то заданий не хватило (пустой реестр) — добираем из других типов
    if len(questions) < 10:
        for qtype in mcq_types:
            if len(questions) >= 10:
                break
            mcq = generate_oge_question_from_registry(qtype=qtype, classes=classes)
            if mcq:
                mcq["type"] = "mcq"
                mcq["points"] = TEST_STRUCTURE[0]["points"]
                questions.append(mcq)

    # Перемешиваем вопросы
    random.shuffle(questions)

    total_points = sum(q.get("points", 0) for q in questions)
    return {
        "test_id": f"test_{random.randint(100000, 999999)}",
        "questions": questions,
        "total_points": total_points,
    }


def check_open_answer(question, user_answer, reference):
    """Проверяет развёрнутый ответ через LLM по критериям ФИПИ.

    Критерии: полнота, точность, соответствие эталону из базы знаний.

    Возвращает dict: {"correct": bool, "score": int, "max_score": int,
    "feedback": str}.
    """
    if not user_answer or not user_answer.strip():
        return {
            "correct": False,
            "score": 0,
            "max_score": 3,
            "feedback": "Ответ не введён.",
        }
    try:
        system_prompt = (
            "Ты — эксперт ЕГЭ по истории. Проверь развёрнутый ответ ученика "
            "на задание по историческому источнику. Оцени по критериям ФИПИ: "
            "полнота, точность, соответствие эталону. "
            "Верни ТОЛЬКО JSON без пояснений в формате: "
            '{"score": 0-3, "correct": true/false, "feedback": "..."}'
        )
        user_prompt = (
            f"ВОПРОС:\n{question}\n\n"
            f"ЭТАЛОННЫЙ ОТВЕТ:\n{reference}\n\n"
            f"ОТВЕТ УЧЕНИКА:\n{user_answer}\n\n"
            "Оцени ответ ученика по 3-балльной шкале (0-3). "
            "correct=true, если score >= 2."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        result = llm_service.call_llm(messages, json_mode=True, max_tokens=500)
        if isinstance(result, list):
            result = result[0] if result else {}
        if not isinstance(result, dict):
            result = {}
        score = int(result.get("score", 0))
        score = max(0, min(3, score))
        correct = bool(result.get("correct", score >= 2))
        feedback = str(result.get("feedback", ""))
        return {
            "correct": correct,
            "score": score,
            "max_score": 3,
            "feedback": feedback,
        }
    except Exception as e:
        logger.error(f"Ошибка проверки развёрнутого ответа: {e}")
        # Fallback: простая проверка по совпадению ключевых слов
        return _fallback_check_open(question, user_answer, reference)


def _fallback_check_open(question, user_answer, reference):
    """Простая проверка развёрнутого ответа без LLM (fallback)."""
    user_lower = user_answer.lower()
    ref_lower = reference.lower()
    # Извлекаем ключевые слова из эталона (слова длиннее 4 символов)
    import re as _re
    words = [w for w in _re.findall(r"[а-яё]{5,}", ref_lower) if w not in (
        "который", "чтобы", "также", "можно", "является", "источник", "ответ"
    )]
    if not words:
        return {"correct": False, "score": 0, "max_score": 3, "feedback": "Не удалось проверить ответ."}
    matched = sum(1 for w in words if w in user_lower)
    ratio = matched / len(words)
    score = 3 if ratio >= 0.6 else (2 if ratio >= 0.4 else (1 if ratio >= 0.2 else 0))
    return {
        "correct": score >= 2,
        "score": score,
        "max_score": 3,
        "feedback": f"Совпадение с эталоном: {int(ratio * 100)}%.",
    }
