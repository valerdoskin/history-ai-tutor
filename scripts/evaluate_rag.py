#!/usr/bin/env python3
"""
Этап 5: Оценка качества RAG-поиска.

Вычисляет метрики качества поиска:
  - recall@k — доля запросов, для которых релевантный чанк найден в топ-k;
  - MRR (Mean Reciprocal Rank) — средний обратный ранг первого релевантного результата;
  - precision@k — доля релевантных результатов в топ-k.

Использование:
    python scripts/evaluate_rag.py                    # полная оценка
    python scripts/evaluate_rag.py --limit 20         # только первые 20 запросов
"""

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
CHUNKS_FILE = os.path.join(KNOWLEDGE_DIR, "chunks.json")
TEST_QUESTIONS_FILE = os.path.join(KNOWLEDGE_DIR, "test_questions.json")


def load_chunks(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_test_questions(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("oge", []) + data.get("ege", [])


def build_query_to_chunk_map(chunks):
    """Строит карту: тема -> список индексов чанков, релевантных теме."""
    topic_map = {}
    for i, chunk in enumerate(chunks):
        topic = chunk.get("topic", "").strip().lower()
        if topic:
            topic_map.setdefault(topic, []).append(i)
    return topic_map


def evaluate(search_fn, chunks, questions, k=5, limit=None):
    """Оценивает качество поиска."""
    if limit:
        questions = questions[:limit]

    topic_map = build_query_to_chunk_map(chunks)

    recall_at_k = []
    mrr_scores = []
    precision_at_k = []

    for q in questions:
        query = q["question"]
        topic = q.get("topic", "").strip().lower()

        # Релевантные чанки для этой темы
        relevant = set(topic_map.get(topic, []))

        if not relevant:
            continue

        # Ищем
        results = search_fn(query, top_k=k)
        retrieved = [r.get("chunk_id") or r.get("id") for r in results]

        # Находим индексы чанков в retrieved
        retrieved_indices = []
        for r in results:
            chunk_id = r.get("chunk_id") or r.get("id")
            # chunk_id может быть индексом или строкой
            if isinstance(chunk_id, int):
                retrieved_indices.append(chunk_id)
            else:
                # Ищем по id в chunks
                for i, c in enumerate(chunks):
                    if c.get("id") == chunk_id:
                        retrieved_indices.append(i)
                        break

        # recall@k
        hits = len(set(retrieved_indices) & relevant)
        recall_at_k.append(hits / len(relevant) if relevant else 0)

        # MRR
        for rank, idx in enumerate(retrieved_indices, 1):
            if idx in relevant:
                mrr_scores.append(1.0 / rank)
                break
        else:
            mrr_scores.append(0.0)

        # precision@k
        precision_at_k.append(hits / k if k > 0 else 0)

    if not recall_at_k:
        logger.warning("Нет запросов с релевантными чанками")
        return {}

    return {
        "recall_at_k": sum(recall_at_k) / len(recall_at_k),
        "mrr": sum(mrr_scores) / len(mrr_scores),
        "precision_at_k": sum(precision_at_k) / len(precision_at_k),
        "num_queries": len(recall_at_k),
    }


def main():
    parser = argparse.ArgumentParser(description="Оценка качества RAG-поиска")
    parser.add_argument("--limit", type=int, default=None, help="Ограничить число запросов")
    parser.add_argument("--k", type=int, default=5, help="Топ-k для оценки")
    args = parser.parse_args()

    chunks = load_chunks(CHUNKS_FILE)
    questions = load_test_questions(TEST_QUESTIONS_FILE)
    logger.info(f"Загружено чанков: {len(chunks)}, вопросов: {len(questions)}")

    # Импортируем сервисы
    from services.embedding_service import get_embedding
    from services.qdrant_service import search as qdrant_search

    def search_fn(query, top_k=5):
        vec = get_embedding(query)
        return qdrant_search(vec, top_k=top_k)

    metrics = evaluate(search_fn, chunks, questions, k=args.k, limit=args.limit)

    if metrics:
        print("\n=== Результаты оценки RAG ===")
        print(f"Запросов оценено: {metrics['num_queries']}")
        print(f"Recall@{args.k}: {metrics['recall_at_k']:.3f}")
        print(f"MRR: {metrics['mrr']:.3f}")
        print(f"Precision@{args.k}: {metrics['precision_at_k']:.3f}")
    else:
        print("Не удалось оценить — нет релевантных чанков.")


if __name__ == "__main__":
    main()
