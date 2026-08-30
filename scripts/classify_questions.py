"""Классификация вопросов реестра по типам для формата ЕГЭ/ОГЭ.

Определяет тип каждого вопроса реестра (факт/хронология/причина-следствие/
понимание/сравнение/термин) на основе эвристик по формулировке вопроса.
Результат сохраняется в knowledge/question_bank.json.

Запуск:
    python scripts/classify_questions.py
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import placement_service as ps

_OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "question_bank.json",
)

# Типы вопросов и их соответствие заданиям ЕГЭ/ОГЭ
TYPE_INFO = {
    "fact": {
        "label": "Знание фактов",
        "ege": [3, 4, 5],
        "oge": [1, 4, 15, 16],
    },
    "chronology": {
        "label": "Хронология / последовательность",
        "ege": [2],
        "oge": [2],
    },
    "cause_effect": {
        "label": "Причины и следствия",
        "ege": [18],
        "oge": [21],
    },
    "understanding": {
        "label": "Понимание / объяснение",
        "ege": [14, 19],
        "oge": [19, 20],
    },
    "comparison": {
        "label": "Сравнение",
        "ege": [20],
        "oge": [23],
    },
    "term": {
        "label": "Термины и понятия",
        "ege": [19],
        "oge": [3, 5],
    },
}

# Эвристики: (regex, тип). Проверяются по порядку, первое совпадение побеждает.
_RULES = [
    # Сравнение
    (r"^(сравните|чем (отличается|отличались|различались|различаются)|в чём (отличие|различие|разница)|каковы (отличия|различия)|какие (отличия|различия))", "comparison"),
    (r"(разница|отличие|различие|отличается|отличались|различались)", "comparison"),
    # Хронология
    (r"^(когда|в каком (году|веке)|расположите|в какой последовательности|какова последовательность|перечислите.*(в хронологическом|по порядку))", "chronology"),
    (r"(в хронологической последовательности|в хронологическом порядке|по порядку)", "chronology"),
    # Причины и следствия
    (r"^(почему|каковы (причины|итоги|последствия|результаты)|какие (причины|итоги|последствия|результаты)|к чему привело|что привело|чем (закончилось|завершилось)|каково (значение|последствие))", "cause_effect"),
    (r"(причины|итоги|последствия|результаты|привело|привела|привели)", "cause_effect"),
    # Термины
    (r"^(что такое|дайте определение|что означает|как называется|как называют|что обозначает|что понимается)", "term"),
    (r"(называется|называют|термин|понятие)", "term"),
    # Понимание / объяснение
    (r"^(в чём|какую роль|каково значение|какое значение|какова роль|объясните|охарактеризуйте|как вы понимаете|почему)", "understanding"),
    (r"(суть|роль|значение|особенность|объясните|охарактеризуйте)", "understanding"),
    # Факт (по умолчанию)
    (r"^(какие|каковы|назовите|что|как|какое|какую|кто|какова|какая|каким|какой|перечислите|где|каков|кого|каких|какими|приведите|докажите|отметьте|можно|благодаря|каково|чему|чего|у|из|с|на|к|в)", "fact"),
]


def classify_question(question):
    """Определяет тип вопроса по формулировке."""
    q = question.strip().lower()
    for pattern, qtype in _RULES:
        if re.search(pattern, q):
            return qtype
    return "fact"


def main():
    # Собираем вопросы реестра по классам (детерминированно, как в
    # generate_placement_test).
    all_questions = []
    for cls in ps.ALL_CLASSES:
        qs = ps._get_exam_questions_for_class(cls)
        seen_q = set()
        unique_qs = []
        for q in qs:
            if q["question"] not in seen_q:
                seen_q.add(q["question"])
                unique_qs.append(q)
        unique_qs.sort(key=lambda q: q["question"])
        for q in unique_qs[: ps.REGISTRY_SIZE]:
            all_questions.append({"class": cls, "question": q["question"], "answer": q["answer"]})

    print(f"Всего вопросов реестра: {len(all_questions)}")

    # ������ѧߧ�֧� ��ا� ��ԧ֧ߧ֧�ڧ��ӧѧߧߧ��� �էڧ���ѧܧ���� �ڧ� ��֧ܧ��֧ԧ� �ҧѧߧܧ� �ӧ�������
    existing = {}
    if os.path.exists(_OUTPUT):
        try:
            existing = json.load(open(_OUTPUT, encoding="utf-8"))
        except Exception:
            existing = {}

    result = {}
    for item in all_questions:
        qtype = classify_question(item["question"])
        prev = existing.get(item["question"], {})
        result[item["question"]] = {
            "class": item["class"],
            "answer": item["answer"],
            "type": qtype,
            "distractors": prev.get("distractors", []),
        }

    with open(_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Статистика по типам
    from collections import Counter
    type_counts = Counter(v["type"] for v in result.values())
    print("\nРаспределение по типам:")
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")

    print(f"\nСохранено в {_OUTPUT}: {len(result)} вопросов")


if __name__ == "__main__":
    main()
