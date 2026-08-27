"""
Сервис эмбеддингов: локальные multilingual-модели (sentence-transformers).

Используется для векторизации чанков и поиска по базе знаний.
"""

import logging

import config

logger = logging.getLogger(__name__)

_model = None


def get_model():
    """Ленивая загрузка модели эмбеддингов."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info(f"Загрузка модели эмбеддингов: {config.EMBEDDING_MODEL}")
        _model = SentenceTransformer(config.EMBEDDING_MODEL)
    return _model


def embed_texts(texts):
    """Возвращает эмбеддинги для списка текстов."""
    model = get_model()
    return model.encode(texts, normalize_embeddings=True)


def embed_query(query):
    """Возвращает эмбеддинг для запроса (с префиксом query для e5)."""
    model = get_model()
    # Для multilingual-e5 требуется префикс "query:" для запросов
    prefixed = f"query: {query}" if not query.startswith("query:") else query
    return model.encode([prefixed], normalize_embeddings=True)[0]
