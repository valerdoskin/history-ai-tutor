"""
Сервис Qdrant: векторная база знаний.

Поддерживает два режима:
- серверный (QDRANT_URL) — для продакшена;
- локальный embedded (QDRANT_PATH) — для разработки без Docker.
"""

import logging

import config

logger = logging.getLogger(__name__)

_client = None


def get_client():
    """Ленивая инициализация клиента Qdrant."""
    global _client
    if _client is None:
        from qdrant_client import QdrantClient

        if config.QDRANT_PATH:
            logger.info(f"Qdrant: локальный режим (path={config.QDRANT_PATH})")
            _client = QdrantClient(path=config.QDRANT_PATH)
        elif config.QDRANT_API_KEY:
            _client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)
        else:
            _client = QdrantClient(url=config.QDRANT_URL)
    return _client


def ensure_collection(dim, recreate=False):
    """Создаёт коллекцию, если её нет."""
    from qdrant_client.http import models

    client = get_client()
    collections = [c.name for c in client.get_collections().collections]
    if config.QDRANT_COLLECTION in collections:
        if recreate:
            client.delete_collection(config.QDRANT_COLLECTION)
            client.create_collection(
                collection_name=config.QDRANT_COLLECTION,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )
            logger.info(f"Коллекция {config.QDRANT_COLLECTION} пересоздана")
        return
    client.create_collection(
        collection_name=config.QDRANT_COLLECTION,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )
    logger.info(f"Коллекция {config.QDRANT_COLLECTION} создана")


def upsert_points(points):
    """Загружает точки в коллекцию."""
    client = get_client()
    client.upsert(collection_name=config.QDRANT_COLLECTION, points=points)


def search(query_vector, top_k=None, score_threshold=None):
    """Ищет релевантные точки по вектору запроса."""
    client = get_client()
    top_k = top_k or config.RAG_TOP_K
    score_threshold = score_threshold if score_threshold is not None else config.RAG_SCORE_THRESHOLD

    # Совместимость с разными версиями qdrant-client:
    # - старые версии используют client.search(query_vector=...)
    # - новые (>=1.10) используют client.query_points(query=...)
    if hasattr(client, "query_points"):
        resp = client.query_points(
            collection_name=config.QDRANT_COLLECTION,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return resp.points
    results = client.search(
        collection_name=config.QDRANT_COLLECTION,
        query_vector=query_vector,
        limit=top_k,
        score_threshold=score_threshold,
        with_payload=True,
    )
    return results


def count_points():
    """Возвращает количество точек в коллекции."""
    client = get_client()
    return client.count(collection_name=config.QDRANT_COLLECTION).count
