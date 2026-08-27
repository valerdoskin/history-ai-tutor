"""
Knowledge Service — доступ к базе знаний (chunks.json).

Предоставляет данные для Web App API:
- список тем (глав),
- детали темы,
- хронологию (даты и события),
- исторических личностей,
- термины.
"""

import json
import logging
import os

import config

logger = logging.getLogger(__name__)

_chunks = None


def _load_chunks():
    """Лениво загружает чанки из chunks.json."""
    global _chunks
    if _chunks is None:
        path = config.CHUNKS_FILE
        if not os.path.exists(path):
            logger.warning("Файл чанков не найден: %s", path)
            _chunks = []
        else:
            with open(path, encoding="utf-8") as f:
                _chunks = json.load(f)
            logger.info("Загружено чанков: %d", len(_chunks))
    return _chunks


def get_class_from_source(source_file):
    """Определяет класс по имени файла-источника."""
    s = (source_file or "").lower()
    if "5_klass" in s:
        return 5
    if "6_klass" in s:
        return 6
    if "7_klass" in s:
        return 7
    if "8_klass" in s:
        return 8
    if "9_klass" in s:
        return 9
    if "10kl" in s or "10_kl" in s or "vseobschaya_10" in s:
        return 10
    return None


def _parse_classes_filter(classes):
    """Преобразует фильтр классов в set или None (все классы)."""
    if not classes or classes == "all":
        return None
    try:
        return {int(c) for c in str(classes).split(",") if c.strip()}
    except (TypeError, ValueError):
        return None


def get_topics(classes=None):
    """Возвращает список тем (глав) с количеством чанков и параграфов.

    classes — фильтр по классам (список int, строка '5,6,7' или 'all').
    """
    chunks = _load_chunks()
    class_filter = _parse_classes_filter(classes)
    topics = {}
    for c in chunks:
        if class_filter is not None:
            cls = get_class_from_source(c.get("source_file", ""))
            if cls not in class_filter:
                continue
        key = (c.get("book_line", ""), c.get("chapter_title", ""))
        if key not in topics:
            topics[key] = {
                "id": len(topics) + 1,
                "book": key[0],
                "title": key[1],
                "chunks": 0,
                "paragraphs": set(),
            }
        topics[key]["chunks"] += 1
        if c.get("paragraph_title"):
            topics[key]["paragraphs"].add(c["paragraph_title"])
    result = []
    for t in topics.values():
        result.append({
            "id": t["id"],
            "book": t["book"],
            "title": t["title"],
            "chunks": t["chunks"],
            "paragraphs": len(t["paragraphs"]),
        })
    result.sort(key=lambda x: (x["book"], x["title"]))
    return result


def get_topic(topic_id):
    """Возвращает детали темы по id: параграфы и их содержимое."""
    chunks = _load_chunks()
    topics = get_topics()
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if not topic:
        return None
    paragraphs = {}
    for c in chunks:
        if c.get("book_line") == topic["book"] and c.get("chapter_title") == topic["title"]:
            ptitle = c.get("paragraph_title") or "Без названия"
            paragraphs.setdefault(ptitle, []).append(c.get("text", ""))
    result = {
        "id": topic["id"],
        "book": topic["book"],
        "title": topic["title"],
        "paragraphs": [
            {"title": p, "text": " ".join(texts)[:4000]}
            for p, texts in paragraphs.items()
        ],
    }
    return result


def _get_meta(chunk):
    """Нормализует metadata чанка в словарь.

    Большинство чанков имеют metadata-словарь вида
    {"dates": [...], "figures": [...], "terms": [...], ...}.
    Один чанк имеет metadata-список дат — нормализуем его в {"dates": [...]}.
    """
    meta = chunk.get("metadata") or {}
    if isinstance(meta, list):
        return {"dates": meta}
    return meta


def get_chronology(limit=200):
    """Возвращает хронологию: даты и события из метаданных чанков."""
    chunks = _load_chunks()
    events = []
    seen = set()
    for c in chunks:
        meta = _get_meta(c)
        for d in meta.get("dates", []):
            year = str(d.get("year", "")).strip()
            event = str(d.get("event", "")).strip()
            if not year or not event:
                continue
            key = (year, event)
            if key in seen:
                continue
            seen.add(key)
            events.append({
                "year": year,
                "event": event,
                "description": d.get("description", ""),
            })
    events.sort(key=lambda x: _year_sort_key(x["year"]))
    return events[:limit]


def _year_sort_key(year):
    """Сортировка по году с учётом до н.э. (например, 'V век до н.э.')."""
    s = str(year).lower()
    if "до н.э" in s or "до н. э" in s:
        return (0, s)
    return (1, s)


def get_figures(limit=200):
    """Возвращает исторических личностей из метаданных чанков."""
    chunks = _load_chunks()
    figures = {}
    for c in chunks:
        meta = _get_meta(c)
        for f in meta.get("figures", []):
            name = str(f.get("name", "")).strip()
            if not name:
                continue
            if name not in figures:
                figures[name] = {
                    "name": name,
                    "years": f.get("years", ""),
                    "role": f.get("role", ""),
                    "description": f.get("description", ""),
                }
    result = sorted(figures.values(), key=lambda x: x["name"])
    return result[:limit]


def get_terms(limit=300):
    """Возвращает термины с определениями из метаданных чанков."""
    chunks = _load_chunks()
    terms = {}
    for c in chunks:
        meta = _get_meta(c)
        for t in meta.get("terms", []):
            term = str(t.get("term", "")).strip()
            if not term:
                continue
            if term not in terms:
                terms[term] = {
                    "term": term,
                    "definition": t.get("definition", ""),
                }
    result = sorted(terms.values(), key=lambda x: x["term"])
    return result[:limit]
