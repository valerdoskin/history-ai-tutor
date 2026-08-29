"""
Сервис изначального теста уровня (placement test).

Генерирует тест из 10 вопросов, покрывающих все классы 5–10
(по 1–2 вопроса на класс), проверяет ответы и определяет
стартовый уровень знаний пользователя (1–5).

Вопросы берутся из готовых exam_questions в metadata чанков базы знаний
(стабильно, без обращения к LLM). Если для класса нет готовых вопросов —
используется генерация через exam_service (LLM) как fallback.
"""

import json
import logging
import os
import random
import time

import numpy as np

from database import db
from services import exam_service, knowledge_service

logger = logging.getLogger(__name__)

# Путь к предвычисленным embeddings вопросов (см. scripts/build_question_embeddings.py)
_QUESTION_EMB_NPY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "question_embeddings.npy",
)
_QUESTION_EMB_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "question_embeddings.json",
)
_ANSWER_EMB_NPY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "answer_embeddings.npy",
)

# Кэш embeddings вопросов: {"questions": [...], "vecs": np.ndarray}
_question_emb_cache = None

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

# Количество вопросов на класс в зависимости от числа выбранных классов.
# Значение — диапазон (мин, макс); фактическое число выбирается случайно
# в пределах диапазона и одинаково для всех выбранных классов.
QUESTIONS_PER_CLASS_BY_COUNT = {
    1: (10, 10),
    2: (8, 9),
    3: (6, 7),
    4: (5, 6),
    5: (4, 5),
    6: (3, 4),
}

# Размер реестра вопросов на класс (из него случайно выбираются вопросы в тест)
REGISTRY_SIZE = 50


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
    """Собирает готовые exam_questions из чанков указанного класса.

    Возвращает список dict: {"question", "answer", "paragraph"}.
    paragraph — заголовок параграфа, из которого взят вопрос (для подбора
    тематически связанных дистракторов).
    """
    chunks = knowledge_service._load_chunks()
    questions = []
    for ch in chunks:
        if get_class_from_source(ch.get("source_file", "")) != cls:
            continue
        meta = ch.get("metadata") or {}
        if isinstance(meta, list):
            meta = {"dates": meta}
        paragraph = str(ch.get("paragraph_title", "")).strip()
        for q in meta.get("exam_questions", []):
            question = str(q.get("question", "")).strip()
            answer = str(q.get("answer", "")).strip()
            if question and answer:
                questions.append({
                    "question": question,
                    "answer": answer,
                    "paragraph": paragraph,
                })
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


def _load_question_embeddings():
    """Загружает предвычисленные embeddings вопросов и ответов (с кэшем).

    Возвращает (questions, qvecs, avecs) или (None, None, None), если файлы
    отсутствуют.
    """
    global _question_emb_cache
    if _question_emb_cache is not None:
        return (
            _question_emb_cache["questions"],
            _question_emb_cache["qvecs"],
            _question_emb_cache["avecs"],
        )
    if not (
        os.path.exists(_QUESTION_EMB_NPY)
        and os.path.exists(_QUESTION_EMB_JSON)
        and os.path.exists(_ANSWER_EMB_NPY)
    ):
        return None, None, None
    try:
        questions = json.load(open(_QUESTION_EMB_JSON, encoding="utf-8"))
        qvecs = np.load(_QUESTION_EMB_NPY)
        avecs = np.load(_ANSWER_EMB_NPY)
        _question_emb_cache = {
            "questions": questions,
            "qvecs": qvecs,
            "avecs": avecs,
        }
        return questions, qvecs, avecs
    except Exception as e:
        logger.error(f"Не удалось загрузить embeddings вопросов: {e}")
        return None, None, None


def _semantic_distractors(question, cls, n=3):
    """Подбирает n семантически близких дистракторов для вопроса.

    Использует предвычисленные embeddings ответов: выбирает ответы,
    наиболее близкие к правильному ответу (косинусная близость), исключая
    сам ответ. Это даёт логичные дистракторы — ответы на похожие вопросы
    (например, про других правителей/основателей государств).
    """
    questions, qvecs, avecs = _load_question_embeddings()
    if questions is None:
        return None
    try:
        idx = next(
            (i for i, q in enumerate(questions) if q["question"] == question),
            None,
        )
        if idx is None:
            return None
        avec = avecs[idx]
        # Косинусная близость ответов (векторы нормализованы)
        sims = avecs @ avec
        order = np.argsort(-sims)
        distractors = []
        used = {questions[idx]["answer"]}
        # Сначала ответы того же класса, затем остальные
        same_class = [i for i in order if questions[i]["class"] == cls]
        other_class = [i for i in order if questions[i]["class"] != cls]
        for i in same_class + other_class:
            if len(distractors) >= n:
                break
            if i == idx:
                continue
            ans = questions[i]["answer"]
            if ans in used:
                continue
            distractors.append(ans)
            used.add(ans)
        return distractors
    except Exception as e:
        logger.error(f"Ошибка подбора семантических дистракторов: {e}")
        return None


def _fallback_distractors(q, cls, classes, n=3):
    """Fallback-подбор дистракторов по параграфу/классу (без embeddings).

    Приоритет: тот же параграф -> тот же класс -> другие классы.
    """
    distractors = []
    used = {q["answer"]}
    # Собираем пул ответов по параграфам для всех классов
    answers_by_class = {}
    for c in classes:
        qs = _get_exam_questions_for_class(c)
        by_para = {}
        for qq in qs:
            by_para.setdefault(qq.get("paragraph", ""), []).append(qq["answer"])
        answers_by_class[c] = by_para

    para = q.get("paragraph", "")
    # 1) Тот же параграф
    same_para = [
        a for a in answers_by_class.get(cls, {}).get(para, [])
        if a != q["answer"]
    ]
    random.shuffle(same_para)
    for a in same_para:
        if len(distractors) >= n:
            break
        if a not in used:
            distractors.append(a)
            used.add(a)
    # 2) Тот же класс (другие параграфы)
    if len(distractors) < n:
        same_class = [
            a for ans in answers_by_class.get(cls, {}).values()
            for a in ans
            if a != q["answer"]
        ]
        random.shuffle(same_class)
        for a in same_class:
            if len(distractors) >= n:
                break
            if a not in used:
                distractors.append(a)
                used.add(a)
    # 3) Другие классы
    if len(distractors) < n:
        other = [
            a for c, by_para in answers_by_class.items()
            if c != cls
            for ans in by_para.values()
            for a in ans
            if a != q["answer"]
        ]
        random.shuffle(other)
        for a in other:
            if len(distractors) >= n:
                break
            if a not in used:
                distractors.append(a)
                used.add(a)
    return distractors


def _questions_per_class(num_classes):
    """Возвращает количество вопросов на класс для заданного числа классов."""
    lo, hi = QUESTIONS_PER_CLASS_BY_COUNT.get(num_classes, (3, 4))
    return random.randint(lo, hi)


def generate_placement_test(user_id=None, num_questions=None):
    """
    Генерирует тест уровня: список вопросов с вариантами ответа.

    Тест формируется по выбранным пользователем классам. Количество вопросов
    на каждый класс зависит от числа выбранных классов (см.
    QUESTIONS_PER_CLASS_BY_COUNT). Вопросы случайно выбираются из реестра
    вопросов каждого класса (REGISTRY_SIZE вопросов).
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

    # Сколько вопросов на каждый класс
    take = _questions_per_class(len(classes))

    # Собираем вопросы по классам: из реестра каждого класса случайно
    # выбираем нужное количество вопросов (без повторений в рамках теста).
    questions = []
    for cls in classes:
        qs = _get_exam_questions_for_class(cls)
        if not qs:
            continue
        # Убираем дубликаты вопросов (один и тот же вопрос встречается
        # в нескольких чанках/параграфах)
        seen_q = set()
        unique_qs = []
        for q in qs:
            if q["question"] not in seen_q:
                seen_q.add(q["question"])
                unique_qs.append(q)
        random.shuffle(unique_qs)
        # Реестр класса — до REGISTRY_SIZE уникальных вопросов
        registry = unique_qs[:REGISTRY_SIZE]
        for q in registry[:take]:
            questions.append((cls, q))

    # Строим MCQ с дистракторами, тематически связанными с вопросом.
    # Основной способ — семантический подбор по embeddings вопросов
    # (наиболее близкие по смыслу вопросы). Если embeddings недоступны —
    # fallback на подбор по параграфу/классу.
    result = []
    for i, (cls, q) in enumerate(questions):
        distractors = _semantic_distractors(q["question"], cls, n=3)
        if distractors is None:
            distractors = _fallback_distractors(q, cls, classes)
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
