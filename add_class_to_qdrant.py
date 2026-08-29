# -*- coding: utf-8 -*-
"""
Добавляет чанки указанного класса в Qdrant без пересоздания коллекции.

Использование:
    python add_class_to_qdrant.py --only "11" [--chunks knowledge/chunks.json]

ВАЖНО: Qdrant использует локальную файловую БД, которая не поддерживает
конкурентный доступ. Перед запуском остановите Flask-сервер.
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
logger = logging.getLogger("add_class_to_qdrant")


def main() -> None:
    parser = argparse.ArgumentParser(description="Добавление чанков класса в Qdrant")
    parser.add_argument("--chunks", default=config.CHUNKS_FILE, help="Путь к chunks.json")
    parser.add_argument("--only", required=True, help="Подстрока source_file для выбора чанков")
    args = parser.parse_args()

    chunks_path = Path(args.chunks)
    if not chunks_path.exists():
        logger.error("Файл чанков не найден: %s", chunks_path)
        sys.exit(1)

    with open(chunks_path, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    only_lower = args.only.lower()
    selected = [c for c in chunks if only_lower in c.get("source_file", "").lower()]
    logger.info("Всего чанков: %d, выбрано для добавления: %d", len(chunks), len(selected))
    if not selected:
        logger.error("Нет чанков, содержащих '%s'", args.only)
        sys.exit(1)

    # Текущее количество точек в коллекции — с него начинаем новые id
    start_id = qdrant_service.count_points()
    logger.info("Текущее количество точек в коллекции: %d", start_id)

    texts = [c["text"] for c in selected]
    logger.info("Векторизация %d текстов...", len(texts))
    vectors = embedding_service.embed_texts(texts)
    logger.info("Векторизация завершена, размерность: %d", vectors.shape[1])

    # Проверяем, что коллекция существует и размерность совпадает
    from qdrant_client.http import models

    from qdrant_client import QdrantClient
    client = qdrant_service.get_client()
    info = client.get_collection(config.QDRANT_COLLECTION)
    if info.config.params.vectors.size != vectors.shape[1]:
        logger.error(
            "Размерность векторов не совпадает: коллекция=%d, новые=%d",
            info.config.params.vectors.size,
            vectors.shape[1],
        )
        sys.exit(1)

    # Формируем точки с уникальными id
    points = []
    for i, chunk in enumerate(selected):
        payload = {
            "id": chunk.get("id", f"chunk_{start_id + i}"),
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
                id=start_id + i,
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
