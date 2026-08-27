#!/usr/bin/env python3
"""
Этап 4: Векторизация чанков и загрузка в Qdrant.

Читает knowledge/chunks.json, генерирует эмбеддинги через sentence-transformers
и загружает их в Qdrant (локально или в облако).

Использование:
    python scripts/vectorize.py                    # полная загрузка
    python scripts/vectorize.py --limit 100        # только первые 100 чанков
    python scripts/vectorize.py --recreate         # пересоздать коллекцию
    python scripts/vectorize.py --dry-run          # только посчитать, без загрузки
"""

import argparse
import json
import logging
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")
CHUNKS_FILE = os.path.join(KNOWLEDGE_DIR, "chunks.json")
# Кэш эмбеддингов (numpy .npy) — чтобы не пересчитывать при повторных запусках
EMBEDDINGS_CACHE = os.path.join(KNOWLEDGE_DIR, "embeddings_cache.npy")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "history_tutor")
# Если задан QDRANT_PATH — используется локальный (embedded) режим Qdrant
QDRANT_PATH = os.getenv("QDRANT_PATH", "")

BATCH_SIZE = 64


def load_chunks(path):
    """Загружает чанки из chunks.json."""
    with open(path, encoding="utf-8") as fh:
        chunks = json.load(fh)
    logger.info(f"Загружено чанков: {len(chunks)}")
    return chunks


def get_embedder():
    """Инициализирует модель эмбеддингов."""
    from sentence_transformers import SentenceTransformer
    logger.info(f"Загрузка модели эмбеддингов: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)
    return model


def embed_texts(model, texts):
    """Генерирует эмбеддинги для списка текстов."""
    # Для e5-моделей рекомендуется префикс "query:" / "passage:"
    prefixed = [f"passage: {t}" for t in texts]
    embeddings = model.encode(prefixed, batch_size=BATCH_SIZE, show_progress_bar=True)
    return embeddings


def get_qdrant_client():
    """Инициализирует клиент Qdrant (локальный или серверный)."""
    from qdrant_client import QdrantClient

    if QDRANT_PATH:
        logger.info(f"Qdrant: локальный режим (path={QDRANT_PATH})")
        return QdrantClient(path=QDRANT_PATH)
    if QDRANT_API_KEY:
        return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return QdrantClient(url=QDRANT_URL)


def ensure_collection(client, dim, recreate=False):
    """Создаёт коллекцию, если её нет."""
    from qdrant_client.http import models

    collections = client.get_collections().collections
    exists = any(c.name == QDRANT_COLLECTION for c in collections)

    if exists and recreate:
        logger.info(f"Пересоздание коллекции: {QDRANT_COLLECTION}")
        client.delete_collection(QDRANT_COLLECTION)
        exists = False

    if not exists:
        logger.info(f"Создание коллекции: {QDRANT_COLLECTION} (dim={dim})")
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=models.VectorParams(
                size=dim,
                distance=models.Distance.COSINE,
            ),
        )
    else:
        logger.info(f"Коллекция уже существует: {QDRANT_COLLECTION}")


def main():
    parser = argparse.ArgumentParser(description="Векторизация чанков и загрузка в Qdrant")
    parser.add_argument("--chunks", default=CHUNKS_FILE, help="Путь к chunks.json")
    parser.add_argument("--limit", type=int, default=None, help="Обработать только первые N чанков")
    parser.add_argument("--recreate", action="store_true", help="Пересоздать коллекцию")
    parser.add_argument("--dry-run", action="store_true", help="Только посчитать, без загрузки")
    args = parser.parse_args()

    chunks = load_chunks(args.chunks)
    if args.limit:
        chunks = chunks[:args.limit]
        logger.info(f"Ограничение: первые {args.limit} чанков")

    if args.dry_run:
        logger.info(f"DRY-RUN: будет загружено {len(chunks)} чанков")
        return

    model = get_embedder()
    texts = [c["text"] for c in chunks]

    # Пытаемся загрузить эмбеддинги из кэша
    embeddings = None
    if os.path.exists(EMBEDDINGS_CACHE):
        try:
            import numpy as np
            cached = np.load(EMBEDDINGS_CACHE)
            if cached.shape[0] == len(texts):
                embeddings = cached
                logger.info(f"Эмбеддинги загружены из кэша: {embeddings.shape}")
            else:
                logger.warning(f"Кэш не совпадает по размеру ({cached.shape[0]} != {len(texts)}), пересчитываю")
        except Exception as e:
            logger.warning(f"Не удалось загрузить кэш эмбеддингов: {e}")

    if embeddings is None:
        logger.info(f"Генерация эмбеддингов для {len(texts)} текстов...")
        embeddings = embed_texts(model, texts)
        # Сохраняем в кэш
        try:
            import numpy as np
            np.save(EMBEDDINGS_CACHE, embeddings)
            logger.info(f"Эмбеддинги сохранены в кэш: {EMBEDDINGS_CACHE}")
        except Exception as e:
            logger.warning(f"Не удалось сохранить кэш эмбеддингов: {e}")

    dim = embeddings.shape[1]
    logger.info(f"Эмбеддинги готовы: {embeddings.shape}")

    client = get_qdrant_client()
    ensure_collection(client, dim, recreate=args.recreate)

    # Загружаем батчами
    from qdrant_client.http import models

    total = len(chunks)
    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        batch_chunks = chunks[start:end]
        batch_embeddings = embeddings[start:end]

        points = []
        for i, (chunk, emb) in enumerate(zip(batch_chunks, batch_embeddings)):
            points.append(
                models.PointStruct(
                    id=start + i,
                    vector=emb.tolist(),
                    payload={
                        "chunk_id": chunk.get("id", ""),
                        "book_id": chunk.get("book_id", ""),
                        "book_line": chunk.get("book_line", ""),
                        "source_file": chunk.get("source_file", ""),
                        "chapter_title": chunk.get("chapter_title", ""),
                        "chapter_number": chunk.get("chapter_number", ""),
                        "paragraph_title": chunk.get("paragraph_title", ""),
                        "paragraph_number": chunk.get("paragraph_number", ""),
                        "main_question": chunk.get("main_question", ""),
                        "chunk_index": chunk.get("chunk_index", 0),
                        "chunk_total": chunk.get("chunk_total", 1),
                        "text": chunk.get("text", ""),
                        "metadata": chunk.get("metadata", {}),
                    },
                )
            )

        client.upsert(
            collection_name=QDRANT_COLLECTION,
            points=points,
        )
        logger.info(f"Загружено {end}/{total}")

    logger.info("=" * 60)
    logger.info(f"ГОТОВО: загружено {total} чанков в коллекцию '{QDRANT_COLLECTION}'")
    logger.info(f"Модель: {EMBEDDING_MODEL}, размерность: {dim}")


if __name__ == "__main__":
    main()
