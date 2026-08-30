"""Предвычисление LLM-дистракторов для вопросов банка.

Заполняет knowledge/question_bank.json дистракторами для вопросов реестра
(REGISTRY_SIZE вопросов на класс, отсортированных детерминированно).
После завершения генерация теста становится мгновенной (все дистракторы
берутся из банка).

Запуск:
    python scripts/precompute_llm_distractors.py [--limit N]
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import placement_service as ps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="Максимальное число вопросов (0 = все)")
    args = parser.parse_args()

    # Собираем вопросы реестра по классам (детерминированно, как в
    # generate_placement_test): сортируем уникальные вопросы по тексту и
    # берём первые REGISTRY_SIZE.
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
            all_questions.append((cls, q))

    if args.limit:
        all_questions = all_questions[: args.limit]

    print(f"Всего вопросов реестра: {len(all_questions)}")

    cache = ps._load_llm_distractors_cache()
    done = 0
    skipped = 0
    failed = 0
    t_start = time.time()

    for i, (cls, q) in enumerate(all_questions, 1):
        question = q["question"]
        answer = q["answer"]
        entry = cache.get(question)
        existing = entry.get("distractors", []) if isinstance(entry, dict) else []
        if len(existing) >= 3:
            skipped += 1
            continue
        distractors = ps._llm_distractors(question, answer, n=3)
        if distractors:
            done += 1
        else:
            failed += 1
        if i % 10 == 0 or i == len(all_questions):
            elapsed = time.time() - t_start
            rate = i / elapsed if elapsed > 0 else 0
            print(
                f"[{i}/{len(all_questions)}] сгенерировано={done} "
                f"пропущено={skipped} ошибок={failed} "
                f"скорость={rate:.1f} вопр/с "
                f"осталось~{(len(all_questions)-i)/rate/60:.1f} мин",
                flush=True,
            )

    print(f"\nГотово: сгенерировано={done}, пропущено={skipped}, ошибок={failed}")
    print(f"Всего в кэше: {len(ps._load_llm_distractors_cache())}")


if __name__ == "__main__":
    main()
