"""
Сервис репетитора: логика диалога, объяснения, проверка знаний.

Использует RAG (grounded_answer) для ответов строго по базе знаний.
"""

import logging

import config
from services import llm_service, rag_service

logger = logging.getLogger(__name__)


def answer_question(query, user_id=None, history=None):
    """
    Отвечает на вопрос пользователя через RAG.
    history — список последних сообщений для контекста диалога.
    """
    return rag_service.grounded_answer(query, user_id=user_id)


def explain_topic(topic, user_id=None):
    """
    Объясняет тему простым языком на основе базы знаний.
    """
    query = f"Объясни тему: {topic}"
    return rag_service.grounded_answer(query, user_id=user_id)


def quiz_question(topic=None, user_id=None):
    """
    Генерирует вопрос для проверки знаний по теме.
    Возвращает dict: {question, options, correct_index, explanation}.
    """
    # Сначала ищем контекст по теме
    query = topic or "ключевые события и даты по истории России"
    chunks = rag_service.retrieve(query, top_k=3)
    context = rag_service.build_context(chunks, max_chars=4000)

    system_prompt = (
        "Ты — составитель тестов по истории для ОГЭ/ЕГЭ. "
        "Составь один вопрос с 4 вариантами ответа на основе контекста. "
        "Верни ТОЛЬКО JSON без пояснений в формате: "
        '{"question": "...", "options": ["...", "...", "...", "..."], '
        '"correct_index": 0, "explanation": "..."}'
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"КОНТЕКСТ:\n{context}\n\nСоставь вопрос по теме: {topic or 'история России'}"},
    ]
    result = llm_service.call_llm(messages, json_mode=True, max_tokens=800)
    return result


def check_answer(question, user_answer, correct_answer, explanation):
    """
    Проверяет ответ пользователя и возвращает обратную связь.
    """
    if user_answer.strip().lower() == correct_answer.strip().lower():
        return {
            "correct": True,
            "feedback": f"Верно! {explanation}",
        }
    return {
        "correct": False,
        "feedback": f"Не совсем. Правильный ответ: {correct_answer}. {explanation}",
    }
