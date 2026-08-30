"""Объединение question_types.json и llm_distractors.json в question_bank.json.

Формат question_bank.json:
{
  "Вопрос": {
    "class": 5,
    "answer": "Ответ",
    "type": "fact",
    "distractors": ["...", "...", "..."]
  }
}

Запуск:
    python scripts/merge_question_bank.py
"""

import json
import os

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_QUESTION_TYPES = os.path.join(_BASE, "knowledge", "question_types.json")
_LLM_DISTRACTORS = os.path.join(_BASE, "knowledge", "llm_distractors.json")
_OUTPUT = os.path.join(_BASE, "knowledge", "question_bank.json")


def main():
    with open(_QUESTION_TYPES, encoding="utf-8") as f:
        question_types = json.load(f)
    with open(_LLM_DISTRACTORS, encoding="utf-8") as f:
        llm_distractors = json.load(f)

    bank = {}
    for question, info in question_types.items():
        bank[question] = {
            "class": info.get("class"),
            "answer": info.get("answer", ""),
            "type": info.get("type", "fact"),
            "distractors": llm_distractors.get(question, []),
        }

    with open(_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)

    with_distractors = sum(1 for v in bank.values() if v["distractors"])
    print(f"Сохранено в {_OUTPUT}: {len(bank)} вопросов")
    print(f"  с дистракторами: {with_distractors}")
    print(f"  без дистракторов: {len(bank) - with_distractors}")


if __name__ == "__main__":
    main()
