"""
Сервис изначального теста уровня (placement test).

Генерирует тест из 10 вопросов, покрывающих все классы 5–10
(по 1–2 вопроса на класс), проверяет ответы и определяет
стартовый уровень знаний пользователя (1–5).

Вопросы берутся из готовых exam_questions в metadata чанков базы знаний
(стабильно, без обращения к LLM). Если для класса нет готовых вопросов —
используется генерация через exam_service (LLM) как fallback.
"""

import logging
import random
import time

from database import db
from services import exam_service, knowledge_service

logger = logging.getLogger(__name__)

# Кэш сгенерированных тестов: user_id -> {"questions": [...], "expires": ts}
_test_cache = {}
_TEST_TTL = 3600  # 1 час

# Классы, представленные в базе знаний
ALL_CLASSES = [5, 6, 7, 8, 9, 10]

# Краткое описание классов (что изучалось)
CLASS_DESCRIPTIONS = {
    5: "Первобытное общество, Древняя Греция, Древний Рим",
    6: "Средневековье; Древняя Русь и создание единого государства",
    7: "Великие географические открытия; Россия в XVI в., Смута, первые Романовы",
    8: "Век перемен; Российская империя: Пётр I, дворцовые перевороты, Екатерина II",
    9: "Индустриальная эпоха; Россия в XIX в.: Николай I, Александр II и III",
    10: "Первая и Вторая мировые войны; Россия 1914–1945 гг., СССР",
}

# Количество вопросов на класс (всего 10)
QUESTIONS_PER_CLASS = {5: 2, 6: 2, 7: 2, 8: 1, 9: 1, 10: 2}


def get_class_from_source(source_file):
    """Определяет класс по имени файла-источника."""
    s = (source_file or "").lower()
    if "5_klass" in s:
        return 5
    if "6_klass" in s:
        return 6
    if "7_klass" in s:
        return 7
    if "8_klass" in s:
        return 8
    if "9_klass" in s:
        return 9
    if "10kl" in s or "10_kl" in s or "vseobschaya_10" in s:
        return 10
    return None


def get_classes_info():
    """Возвращает список классов с описанием и количеством чанков."""
    chunks = knowledge_service._load_chunks()
    counts = {c: 0 for c in ALL_CLASSES}
    for ch in chunks:
        cls = get_class_from_source(ch.get("source_file", ""))
        if cls in counts:
            counts[cls] += 1
    return [
        {
            "class": c,
            "description": CLASS_DESCRIPTIONS[c],
            "chunks": counts[c],
        }
        for c in ALL_CLASSES
    ]


def _parse_selected_classes(selected):
    """Преобразует сохранённое значение в список классов (или 'all')."""
    if not selected or selected == "all":
        return "all"
    try:
        return [int(x) for x in str(selected).split(",") if x.strip()]
    except (TypeError, ValueError):
        return "all"


def _get_exam_questions_for_class(cls):
    """Собирает готовые exam_questions из чанков указанного класса."""
    chunks = knowledge_service._load_chunks()
    questions = []
    for ch in chunks:
        if get_class_from_source(ch.get("source_file", "")) != cls:
            continue
        meta = ch.get("metadata") or {}
        if isinstance(meta, list):
            meta = {"dates": meta}
        for q in meta.get("exam_questions", []):
            question = str(q.get("question", "")).strip()
            answer = str(q.get("answer", "")).strip()
            if question and answer:
                questions.append({"question": question, "answer": answer})
    return questions


def _make_mcq(question, answer):
    """Превращает открытый вопрос в вопрос с 4 вариантами ответа.

    Правильный ответ + 3 дистрактора (из других вопросов того же класса).
    """
    return {
        "question": question,
        "options": [answer],
        "correct_index": 0,
        "explanation": "",
        "topic": "",
    }


def _build_mcq_with_distractors(question, answer, distractors):
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


def generate_placement_test(user_id=None, num_questions=10):
    """
    Генерирует тест уровня: список вопросов с вариантами ответа.

    Покрывает все классы 5–10. Если пользователь выбрал классы —
    вопросы берутся только из выбранных классов.
    """
    selected = "all"
    if user_id:
        selected = db.get_selected_classes(user_id)
    selected = _parse_selected_classes(selected)

    # Определяем, какие классы использовать
    if selected == "all":
        classes = ALL_CLASSES
    else:
        classes = [c for c in ALL_CLASSES if c in selected]
        if not classes:
            classes = ALL_CLASSES

    # Собираем вопросы по классам
    questions = []
    for cls in classes:
        qs = _get_exam_questions_for_class(cls)
        if not qs:
            continue
        random.shuffle(qs)
        # Берём по 1 вопросу на класс (или 2 для первых классов)
        take = QUESTIONS_PER_CLASS.get(cls, 1)
        for q in qs[:take]:
            questions.append((cls, q))

    # Если вопросов мало — добираем из других классов
    if len(questions) < num_questions:
        for cls in ALL_CLASSES:
            if len(questions) >= num_questions:
                break
            if cls in classes:
                continue
            qs = _get_exam_questions_for_class(cls)
            random.shuffle(qs)
            for q in qs:
                if len(questions) >= num_questions:
                    break
                questions.append((cls, q))

    # Ограничиваем до num_questions
    questions = questions[:num_questions]

    # Строим MCQ с дистракторами из других вопросов
    all_answers = [q["answer"] for _, q in questions]
    result = []
    for i, (cls, q) in enumerate(questions):
        distractors = [a for a in all_answers if a != q["answer"]]
        random.shuffle(distractors)
        mcq = _build_mcq_with_distractors(q["question"], q["answer"], distractors)
        mcq["id"] = i
        mcq["class"] = cls
        result.append(mcq)

    # Сохраняем тест в кэш для последующей проверки
    if user_id:
        _test_cache[user_id] = {
            "questions": result,
            "expires": time.time() + _TEST_TTL,
        }

    return result


def _get_cached_test(user_id):
    """Возвращает закэшированный тест пользователя (или None)."""
    entry = _test_cache.get(user_id)
    if not entry:
        return None
    if entry["expires"] < time.time():
        _test_cache.pop(user_id, None)
        return None
    return entry["questions"]


def check_placement_test(user_id, answers):
    """
    Проверяет ответы на тест уровня по закэшированному тесту.

    answers — список dict: {"question_id": int, "answer_index": int}.
    Возвращает dict: {score, total, level, rank}.
    """
    questions = _get_cached_test(user_id) if user_id else None
    if not questions:
        return {"error": "Тест не найден или истёк. Начните тест заново."}

    by_id = {q["id"]: q for q in questions}
    score = 0
    total = len(answers)
    for a in answers:
        q = by_id.get(a.get("question_id"))
        if q and a.get("answer_index") == q.get("correct_index"):
            score += 1

    level = _score_to_level(score, total)
    return {
        "score": score,
        "total": total,
        "level": level,
        "rank": _level_to_rank(level),
    }


def _score_to_level(score, total):
    """Переводит количество правильных ответов в уровень 1–5."""
    if total == 0:
        return 1
    ratio = score / total
    if ratio >= 0.9:
        return 5
    if ratio >= 0.7:
        return 4
    if ratio >= 0.5:
        return 3
    if ratio >= 0.3:
        return 2
    return 1


def _level_to_rank(level):
    ranks = {1: "Новичок", 2: "Начинающий", 3: "Средний", 4: "Продвинутый", 5: "Эксперт"}
    return ranks.get(level, "Новичок")


def submit_placement(user_id, answers):
    """
    Сохраняет результат теста уровня и возвращает итог.
    """
    result = check_placement_test(user_id, answers)
    if "error" in result:
        return result
    db.save_placement_result(
        user_id, result["score"], result["total"], result["level"]
    )
    return result
