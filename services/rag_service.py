"""
RAG-сервис: поиск по базе знаний + grounding.

Ключевой принцип: LLM отвечает ТОЛЬКО на основе найденных чанков
(локальная база знаний), без галлюцинаций и внешних источников.
"""

import logging

import config
from services import embedding_service, qdrant_service

logger = logging.getLogger(__name__)


def retrieve(query, top_k=None, class_filter=None):
    """
    Ищет релевантные чанки по запросу.
    Возвращает список словарей с текстом и метаданными.

    class_filter — фильтр по классам (строка '5,6,7' или 'all').
    """
    query_vector = embedding_service.embed_query(query)
    results = qdrant_service.search(query_vector, top_k=top_k, class_filter=class_filter)
    chunks = []
    for r in results:
        payload = r.payload or {}
        chunks.append(
            {
                "text": payload.get("text", ""),
                "score": round(r.score, 4),
                "book": payload.get("book", ""),
                "chapter": payload.get("chapter", ""),
                "paragraph": payload.get("paragraph", ""),
                "section": payload.get("section", ""),
                "dates": payload.get("dates", []),
                "figures": payload.get("figures", []),
                "terms": payload.get("terms", []),
                "key_facts": payload.get("key_facts", []),
            }
        )
    return chunks


def build_context(chunks, max_chars=8000):
    """Собирает контекст из найденных чанков для подачи в LLM."""
    parts = []
    total = 0
    for i, c in enumerate(chunks, 1):
        header = f"[Чанк {i}]"
        if c.get("book"):
            header += f" Книга: {c['book']}"
        if c.get("chapter"):
            header += f" | Глава: {c['chapter']}"
        if c.get("paragraph"):
            header += f" | Параграф: {c['paragraph']}"
        if c.get("section"):
            header += f" | Раздел: {c['section']}"
        block = f"{header}\n{c['text']}"
        if total + len(block) > max_chars:
            break
        parts.append(block)
        total += len(block)
    return "\n\n".join(parts)


def grounded_answer(query, user_id=None, top_k=None, class_filter=None):
    """
    Полный RAG-ответ: поиск чанков + генерация ответа LLM строго по ним.
    Возвращает dict: {answer, sources, chunks}.

    class_filter — фильтр по классам (строка '5,6,7' или 'all').
    """
    from services import llm_service

    chunks = retrieve(query, top_k=top_k, class_filter=class_filter)
    if not chunks:
        return {
            "answer": "К сожалению, я не нашёл информации по этому вопросу в базе знаний. "
                      "Попробуйте переформулировать запрос или спросить о другой теме.",
            "sources": [],
            "chunks": [],
        }

    context = build_context(chunks)
    system_prompt = (
        "Ты — ИИ-репетитор по истории для подготовки школьников к ОГЭ и ЕГЭ. "
        "Отвечай ТОЛЬКО на основе предоставленного контекста из учебников. "
        "Не используй внешние знания и не выдумывай факты. "
        "Если в контексте нет ответа — честно скажи об этом. "
        "Отвечай на русском языке, структурированно, понятным школьнику языком. "
        "В конце укажи источники (книга, глава, параграф).\n\n"
        f"КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ:\n{context}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]
    answer = llm_service.call_llm(messages, max_tokens=config.LLM_MAX_TOKENS)

    sources = []
    seen = set()
    for c in chunks:
        key = (c.get("book"), c.get("chapter"), c.get("paragraph"))
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            {
                "book": c.get("book"),
                "chapter": c.get("chapter"),
                "paragraph": c.get("paragraph"),
                "score": c.get("score"),
            }
        )

    return {"answer": answer, "sources": sources, "chunks": chunks}
