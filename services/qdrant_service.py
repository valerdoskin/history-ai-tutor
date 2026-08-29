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


def _build_class_filter(class_filter):
    """Строит Qdrant-фильтр по классам (по source_file)."""
    if not class_filter or class_filter == "all":
        return None
    from qdrant_client.http import models

    try:
        classes = {int(c) for c in str(class_filter).split(",") if c.strip()}
    except (TypeError, ValueError):
        return None

    # Сопоставление класса с подстроками в source_file
    class_patterns = {
        5: ["5_klass"],
        6: ["6_klass"],
        7: ["7_klass"],
        8: ["8_klass"],
        9: ["9_klass"],
        10: ["10kl", "10_kl", "vseobschaya_10"],
        11: ["11kl", "11_kl", "vseobschaya_11"],
    }
    patterns = []
    for cls in classes:
        patterns.extend(class_patterns.get(cls, []))
    if not patterns:
        return None

    # OR по паттернам source_file
    return models.Filter(
        should=[
            models.FieldCondition(
                key="source_file",
                match=models.MatchText(text=p),
            )
            for p in patterns
        ]
    )


def search(query_vector, top_k=None, score_threshold=None, class_filter=None):
    """Ищет релевантные точки по вектору запроса.

    class_filter — фильтр по классам (строка '5,6,7' или 'all').
    """
    client = get_client()
    top_k = top_k or config.RAG_TOP_K
    score_threshold = score_threshold if score_threshold is not None else config.RAG_SCORE_THRESHOLD
    query_filter = _build_class_filter(class_filter)

    # Совместимость с разными версиями qdrant-client:
    # - старые версии используют client.search(query_vector=...)
    # - новые (>=1.10) используют client.query_points(query=...)
    if hasattr(client, "query_points"):
        resp = client.query_points(
            collection_name=config.QDRANT_COLLECTION,
            query=query_vector,
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=query_filter,
            with_payload=True,
        )
        return resp.points
    results = client.search(
        collection_name=config.QDRANT_COLLECTION,
        query_vector=query_vector,
        limit=top_k,
        score_threshold=score_threshold,
        query_filter=query_filter,
        with_payload=True,
    )
    return results


def count_points():
    """Возвращает количество точек в коллекции."""
    client = get_client()
    return client.count(collection_name=config.QDRANT_COLLECTION).count
