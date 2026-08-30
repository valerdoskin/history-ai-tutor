# -*- coding: utf-8 -*-
"""
Выборочная пересборка Qdrant только для книг, чьи чанки изменились.

Сравнивает тексты чанков в chunks.json с текстами точек в Qdrant.
Для книг, где тексты отличаются:
  1. Удаляет старые точки этой книги из Qdrant.
  2. Векторизует новые чанки из chunks.json.
  3. Загружает их в Qdrant.

Использование:
    python rebuild_qdrant_selective.py [--chunks knowledge/chunks.json] [--books "Vseobschaya_11.pdf,Za_8_klass.docx"]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import zlib
from collections import defaultdict
from pathlib import Path

import config
from services import embedding_service, qdrant_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rebuild_qdrant_selective")


def load_chunks(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_qdrant_texts_by_book() -> dict[str, list[str]]:
    """Возвращает {source_file: [text, ...]} из Qdrant."""
    client = qdrant_service.get_client()
    offset = None
    by_book: dict[str, list[str]] = defaultdict(list)
    while True:
        points, offset = client.scroll(
            collection_name=config.QDRANT_COLLECTION,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            by_book[p.payload.get("source_file", "")].append(p.payload.get("text", ""))
        if offset is None:
            break
    return by_book


def find_changed_books(chunks: list[dict], qdrant_by_book: dict[str, list[str]]) -> list[str]:
    """Возвращает список книг, чьи тексты чанков отличаются от Qdrant."""
    chunk_by_book: dict[str, list[str]] = defaultdict(list)
    for c in chunks:
        chunk_by_book[c["source_file"]].append(c["text"])

    all_books = set(chunk_by_book.keys()) | set(qdrant_by_book.keys())
    changed = []
    for book in sorted(all_books):
        c_texts = sorted(chunk_by_book.get(book, []))
        q_texts = sorted(qdrant_by_book.get(book, []))
        if c_texts != q_texts:
            changed.append(book)
    return changed


def rebuild_book(book: str, chunks: list[dict]) -> int:
    """Пересобирает одну книгу в Qdrant. Возвращает число загруженных точек."""
    from qdrant_client.http import models

    client = qdrant_service.get_client()

    # 1. Удаляем старые точки книги
    book_chunks = [c for c in chunks if c["source_file"] == book]
    if not book_chunks:
        logger.warning("Книга %s не найдена в chunks.json, пропускаю", book)
        return 0

    # Удаляем по фильтру source_file
    client.delete(
        collection_name=config.QDRANT_COLLECTION,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_file",
                        match=models.MatchValue(value=book),
                    )
                ]
            )
        ),
    )
    logger.info("Книга %s: старые точки удалены", book)

    # 2. Векторизуем новые чанки
    texts = [c["text"] for c in book_chunks]
    logger.info("Книга %s: векторизация %d чанков...", book, len(texts))
    vectors = embedding_service.embed_texts(texts)

    # 3. Формируем точки
    points = []
    for i, chunk in enumerate(book_chunks):
        payload = {
            "id": chunk.get("id", f"chunk_{i}"),
            "book_id": chunk.get("book_id", ""),
            "book_line": chunk.get("book_line", ""),
            "source_file": chunk.get("source_file", ""),
            "chapter_title": chunk.get("chapter_title", ""),
            "chapter_number": chunk.get("chapter_number", ""),
            "paragraph_title": chunk.get("paragraph_title", ""),
            "paragraph_number": chunk.get("paragraph_number", ""),
            "page_start": chunk.get("page_start"),
            "page_end": chunk.get("page_end"),
            "main_question": chunk.get("main_question", ""),
            "chunk_index": chunk.get("chunk_index", 0),
            "chunk_total": chunk.get("chunk_total", 1),
            "text": chunk.get("text", ""),
            "metadata": chunk.get("metadata", {}),
        }
        # Qdrant требует числовые ID или UUID. Используем стабильный crc32 хэш строкового id.
        chunk_id = chunk.get("id", f"{book}::{i}")
        numeric_id = zlib.crc32(chunk_id.encode("utf-8"))
        points.append(
            models.PointStruct(
                id=numeric_id,
                vector=vectors[i].tolist(),
                payload=payload,
            )
        )

    # 4. Загружаем батчами
    batch_size = 100
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        qdrant_service.upsert_points(batch)
        logger.info("Книга %s: загружено %d/%d точек", book, min(start + batch_size, len(points)), len(points))

    return len(points)


def main() -> None:
    parser = argparse.ArgumentParser(description="Выборочная пересборка Qdrant")
    parser.add_argument("--chunks", default=config.CHUNKS_FILE, help="Путь к chunks.json")
    parser.add_argument("--books", default=None, help="Список книг через запятую (source_file). Если не указан — определяются автоматически.")
    args = parser.parse_args()

    chunks_path = Path(args.chunks)
    if not chunks_path.exists():
        logger.error("Файл чанков не найден: %s", chunks_path)
        sys.exit(1)

    chunks = load_chunks(chunks_path)
    logger.info("Загружено чанков: %d", len(chunks))

    # Определяем книги для пересборки
    if args.books:
        books = [b.strip() for b in args.books.split(",") if b.strip()]
        logger.info("Книги для пересборки (заданы вручную): %s", books)
    else:
        qdrant_by_book = load_qdrant_texts_by_book()
        books = find_changed_books(chunks, qdrant_by_book)
        logger.info("Книги для пересборки (определены автоматически): %s", books)

    if not books:
        logger.info("Нет книг для пересборки — все тексты совпадают.")
        return

    total_loaded = 0
    for book in books:
        loaded = rebuild_book(book, chunks)
        total_loaded += loaded
        logger.info("Книга %s: загружено %d точек", book, loaded)

    total = qdrant_service.count_points()
    logger.info("Готово! Загружено %d точек, всего в коллекции: %d", total_loaded, total)


if __name__ == "__main__":
    main()
