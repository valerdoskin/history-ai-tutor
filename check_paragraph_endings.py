# -*- coding: utf-8 -*-
"""
Проверка корректности парсинга по всем книгам через LLM.

Для каждой книги выбирает 2 случайных параграфа, берёт последние 3000 символов
каждого и проверяет через LLM, что текст заканчивается логично и точкой.

Использование:
    python check_paragraph_endings.py [--chunks knowledge/chunks.json] [--seed N]
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from collections import defaultdict
from pathlib import Path

import config
from services.llm_service import call_llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("check_paragraph_endings")

TAIL_LENGTH = 3000
PARAGRAPHS_PER_BOOK = 2


def load_chunks(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def group_paragraphs(chunks: list[dict]) -> dict[str, dict[str, list[dict]]]:
    """Группирует чанки по книге (source_file) и параграфу (paragraph_title)."""
    books: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for c in chunks:
        books[c["source_file"]][c["paragraph_title"]].append(c)
    return books


def build_paragraph_text(para_chunks: list[dict]) -> str:
    """Собирает полный текст параграфа из чанков, отсортированных по chunk_index."""
    para_chunks = sorted(para_chunks, key=lambda c: c.get("chunk_index", 0))
    return "\n".join(c["text"] for c in para_chunks)


def check_tail_with_llm(book: str, paragraph: str, tail: str) -> dict:
    """Отправляет хвост параграфа в LLM и возвращает результат проверки."""
    prompt = (
        "Ты — эксперт по проверке качества парсинга учебников истории. "
        "Ниже приведён КОНЕЦ параграфа учебника (последние ~3000 символов). "
        "Проверь, что текст заканчивается ЛОГИЧНО и ЗАВЕРШЁННО (точкой, завершённой мыслью), "
        "а не обрывается на полуслове, середине предложения или в нелогичном месте.\n\n"
        "Верни ТОЛЬКО JSON-объект вида:\n"
        '{"ok": true/false, "reason": "краткое объяснение"}\n\n'
        "ok=true — если текст заканчивается логично и точкой.\n"
        "ok=false — если текст обрывается на полуслове/середине предложения/нелогично.\n\n"
        f"Книга: {book}\nПараграф: {paragraph}\n\n"
        f"КОНЕЦ ПАРАГРАФА:\n{tail}"
    )
    result = call_llm(
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=300,
        json_mode=True,
    )
    if isinstance(result, dict):
        return result
    return {"ok": False, "reason": f"Некорректный ответ LLM: {result}"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка корректности парсинга через LLM")
    parser.add_argument("--chunks", default=config.CHUNKS_FILE, help="Путь к chunks.json")
    parser.add_argument("--seed", type=int, default=None, help="Seed для воспроизводимости")
    args = parser.parse_args()

    chunks_path = Path(args.chunks)
    if not chunks_path.exists():
        logger.error("Файл чанков не найден: %s", chunks_path)
        return

    chunks = load_chunks(chunks_path)
    books = group_paragraphs(chunks)

    rng = random.Random(args.seed)
    logger.info("Книг найдено: %d", len(books))

    results = []
    for book in sorted(books.keys()):
        paragraphs = list(books[book].keys())
        if len(paragraphs) < 2:
            logger.warning("Книга %s: только %d параграфов, беру все", book, len(paragraphs))
            selected = paragraphs
        else:
            selected = rng.sample(paragraphs, PARAGRAPHS_PER_BOOK)

        for para in selected:
            para_chunks = books[book][para]
            full_text = build_paragraph_text(para_chunks)
            tail = full_text[-TAIL_LENGTH:]
            logger.info("Проверяю: %s :: %s (длина %d, хвост %d)", book, para, len(full_text), len(tail))
            try:
                verdict = check_tail_with_llm(book, para, tail)
            except Exception as e:  # noqa: BLE001
                verdict = {"ok": False, "reason": f"Ошибка LLM: {e}"}
            results.append({
                "book": book,
                "paragraph": para,
                "full_length": len(full_text),
                "tail_length": len(tail),
                "ok": verdict.get("ok", False),
                "reason": verdict.get("reason", ""),
            })
            logger.info("  -> ok=%s, reason=%s", verdict.get("ok"), verdict.get("reason", "")[:100])

    # Отчёт
    print("\n" + "=" * 80)
    print("ОТЧЁТ ПО ПРОВЕРКЕ КОРРЕКТНОСТИ ПАРСИНГА")
    print("=" * 80)
    problems = 0
    for r in results:
        status = "OK" if r["ok"] else "ПРОБЛЕМА"
        if not r["ok"]:
            problems += 1
        print(f"[{status}] {r['book']} :: {r['paragraph']}")
        print(f"    длина={r['full_length']}, хвост={r['tail_length']}")
        if not r["ok"]:
            print(f"    причина: {r['reason']}")
    print("=" * 80)
    print(f"Итого: {len(results)} проверок, проблем: {problems}")
    if problems:
        print("ЕСТЬ ПРОБЛЕМЫ — требуется доработка парсеров!")
    else:
        print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ — парсинг корректен.")


if __name__ == "__main__":
    main()
