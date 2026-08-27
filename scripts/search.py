#!/usr/bin/env python3
"""
Поиск по векторной базе (RAG retrieval).

Используется ботом для поиска релевантных чанков по запросу ученика.

Использование:
    python scripts/search.py "Восстание декабристов"
    python scripts/search.py "Кто такой Хаммурапи?" --top 5
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "history_tutor")
# Если задан QDRANT_PATH — используется локальный (embedded) режим Qdrant
QDRANT_PATH = os.getenv("QDRANT_PATH", "")


def get_embedder():
    from sentence_transformers import SentenceTransformer
    logger.info(f"Загрузка модели эмбеддингов: {EMBEDDING_MODEL}")
    return SentenceTransformer(EMBEDDING_MODEL)


def get_qdrant_client():
    from qdrant_client import QdrantClient
    if QDRANT_PATH:
        logger.info(f"Qdrant: локальный режим (path={QDRANT_PATH})")
        return QdrantClient(path=QDRANT_PATH)
    if QDRANT_API_KEY:
        return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return QdrantClient(url=QDRANT_URL)


def search(query, top_k=5):
    """Ищет релевантные чанки по запросу."""
    model = get_embedder()
    client = get_qdrant_client()

    # Для e5-моделей используем префикс "query:"
    query_embedding = model.encode([f"query: {query}"])[0]

    # Совместимость с разными версиями qdrant-client:
    # - старые версии используют client.search(query_vector=...)
    # - новые (>=1.10) используют client.query_points(query=...)
    if hasattr(client, "query_points"):
        resp = client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=query_embedding.tolist(),
            limit=top_k,
            with_payload=True,
        )
        return resp.points
    results = client.search(
        collection_name=QDRANT_COLLECTION,
        query_vector=query_embedding.tolist(),
        limit=top_k,
    )
    return results


def main():
    parser = argparse.ArgumentParser(description="Поиск по векторной базе")
    parser.add_argument("query", help="Поисковый запрос")
    parser.add_argument("--top", type=int, default=5, help="Количество результатов")
    args = parser.parse_args()

    results = search(args.query, top_k=args.top)

    if not results:
        print("Ничего не найдено.")
        return

    print(f"Найдено {len(results)} результатов для: '{args.query}'\n")
    for i, r in enumerate(results, 1):
        payload = r.payload
        print(f"--- Результат {i} (score={r.score:.4f}) ---")
        print(f"Книга: {payload.get('book_line', '')} / {payload.get('chapter_title', '')}")
        print(f"Параграф: {payload.get('paragraph_title', '')}")
        print(f"Текст: {payload.get('text', '')[:200]}...")
        print()


if __name__ == "__main__":
    main()
