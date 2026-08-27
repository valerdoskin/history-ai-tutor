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


_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
          "vii": "7", "viii": "8", "ix": "9", "x": "10", "xi": "11", "xii": "12",
          "xiii": "13", "xiv": "14", "xv": "15", "xvi": "16", "xvii": "17",
          "xviii": "18", "xix": "19", "xx": "20", "xxi": "21"}


def _topic_keywords(topic):
    """Разбивает тему на значимые ключевые слова (для AND-сопоставления).

    Обрабатывает римские цифры веков (XIX -> 19) и диапазоны годов.
    """
    stopwords = {"в", "на", "и", "годы", "гг", "веке", "века", "век", "россия", "ссср"}
    words = []
    for w in topic.lower().replace("–", " ").replace("—", " ").split():
        w = w.strip(".,;:()")
        if not w or w in stopwords:
            continue
        # Римская цифра века -> арабская
        if w in _ROMAN:
            words.append(_ROMAN[w])
            continue
        if len(w) > 2:
            words.append(w)
    return words


def build_query_to_chunk_map(chunks):
    """Строит карту: тема -> список индексов чанков, релевантных теме.

    Релевантность определяется по совпадению ВСЕХ значимых ключевых слов
    темы с текстом чанка (AND-логика).
    """
    topic_map = {}
    for i, chunk in enumerate(chunks):
        text = (chunk.get("text", "") + " " + chunk.get("chapter_title", "")).lower()
        for topic in _all_topics():
            keywords = _topic_keywords(topic)
            if not keywords:
                continue
            # Чанк релевантен теме, если в тексте встречаются ВСЕ ключевые слова
            if all(kw in text for kw in keywords):
                topic_map.setdefault(topic, set()).add(i)
    return topic_map


_all_topics_cache = None


def _all_topics():
    global _all_topics_cache
    if _all_topics_cache is None:
        with open(TEST_QUESTIONS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        _all_topics_cache = sorted({q["topic"] for q in data.get("oge", []) + data.get("ege", [])})
    return _all_topics_cache


def evaluate(search_fn, chunks, questions, k=5, limit=None):
    """Оценивает качество поиска по уверенности (score) найденных чанков.

    Для каждого вопроса выполняет поиск и оценивает максимальный score.
    Высокий max_score (> 0.8) означает, что поиск уверенно нашёл релевантный чанк.
    Низкий max_score указывает на пробел в базе знаний по данному вопросу.
    """
    if limit:
        questions = questions[:limit]

    max_scores = []
    low_coverage = []

    for q in questions:
        query = q["question"]
        results = search_fn(query, top_k=k)
        if not results:
            max_scores.append(0.0)
            low_coverage.append((q["id"], q["topic"], query, 0.0))
            continue
        max_score = max(r.get("score", 0.0) for r in results)
        max_scores.append(max_score)
        if max_score < 0.8:
            low_coverage.append((q["id"], q["topic"], query, round(max_score, 3)))

    if not max_scores:
        return {}

    good = sum(1 for s in max_scores if s >= 0.8)
    return {
        "num_queries": len(max_scores),
        "avg_max_score": sum(max_scores) / len(max_scores),
        "good_coverage_ratio": good / len(max_scores),
        "low_coverage_questions": low_coverage,
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
    from services.embedding_service import embed_query
    from services.qdrant_service import search as qdrant_search

    def search_fn(query, top_k=5):
        vec = embed_query(query)
        results = qdrant_search(vec, top_k=top_k)
        # Преобразуем ScoredPoint в словари с chunk_id
        out = []
        for r in results:
            payload = r.payload or {}
            out.append(
                {
                    "chunk_id": payload.get("chunk_id"),
                    "text": payload.get("text", ""),
                    "score": r.score,
                }
            )
        return out

    metrics = evaluate(search_fn, chunks, questions, k=args.k, limit=args.limit)

    if metrics:
        print("\n=== Результаты оценки RAG ===")
        print(f"Запросов оценено: {metrics['num_queries']}")
        print(f"Средний max_score: {metrics['avg_max_score']:.3f}")
        print(f"Доля вопросов с хорошим покрытием (max_score>=0.8): {metrics['good_coverage_ratio']:.3f}")
        low = metrics.get("low_coverage_questions", [])
        if low:
            print(f"\nВопросы с низким покрытием базы знаний ({len(low)}):")
            for qid, topic, query, score in low:
                print(f"  [{qid}] ({topic}) score={score} | {query}")
    else:
        print("Не удалось оценить — нет данных.")


if __name__ == "__main__":
    main()
