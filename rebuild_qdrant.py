# -*- coding: utf-8 -*-
"""
Пересборка векторной базы Qdrant из chunks.json.

Векторизует все чанки и загружает их в Qdrant (пересоздавая коллекцию).

ВАЖНО: Qdrant использует локальную файловую БД, которая не поддерживает
конкурентный доступ. Перед запуском остановите Flask-сервер.

Использование:
    python rebuild_qdrant.py [--chunks knowledge/chunks.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import config
from services import embedding_service, qdrant_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rebuild_qdrant")


def main() -> None:
    parser = argparse.ArgumentParser(description="Пересборка Qdrant из chunks.json")
    parser.add_argument("--chunks", default=config.CHUNKS_FILE, help="Путь к chunks.json")
    args = parser.parse_args()

    chunks_path = Path(args.chunks)
    if not chunks_path.exists():
        logger.error("Файл чанков не найден: %s", chunks_path)
        sys.exit(1)

    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    logger.info("Загружено чанков: %d", len(chunks))
    if not chunks:
        logger.error("Нет чанков для загрузки")
        sys.exit(1)

    texts = [c["text"] for c in chunks]
    logger.info("Векторизация %d текстов...", len(texts))
    vectors = embedding_service.embed_texts(texts)
    logger.info("Векторизация завершена, размерность: %d", vectors.shape[1])

    # Пересоздаём коллекцию
    qdrant_service.ensure_collection(vectors.shape[1], recreate=True)

    # Формируем точки
    from qdrant_client.http import models

    points = []
    for i, chunk in enumerate(chunks):
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
        points.append(
            models.PointStruct(
                id=i,
                vector=vectors[i].tolist(),
                payload=payload,
            )
        )

    # Загружаем батчами
    batch_size = 100
    for start in range(0, len(points), batch_size):
        batch = points[start : start + batch_size]
        qdrant_service.upsert_points(batch)
        logger.info("Загружено %d/%d точек", min(start + batch_size, len(points)), len(points))

    total = qdrant_service.count_points()
    logger.info("Готово! В коллекции %s точек: %d", config.QDRANT_COLLECTION, total)


if __name__ == "__main__":
    main()
