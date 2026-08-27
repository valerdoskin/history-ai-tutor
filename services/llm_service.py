"""
LLM-сервис: DeepSeek (основной) с fallback на Groq.

Используется для генерации ответов репетитора, объяснений,
генерации заданий ОГЭ/ЕГЭ и обогащения метаданных.
"""

import json
import logging
import time

import requests

import config

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def _call_openai_compatible(url, api_key, model, messages, temperature, max_tokens):
    """Универсальный вызов OpenAI-совместимого API."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        raise LLMError(f"API {model} вернул {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def call_llm(
    messages,
    temperature=None,
    max_tokens=None,
    json_mode=False,
    retries=3,
    retry_delay=1.0,
):
    """
    Вызывает LLM с fallback-цепочкой: DeepSeek -> Groq.

    messages: список [{"role": "system"|"user"|"assistant", "content": "..."}]
    json_mode: если True, просит модель вернуть чистый JSON.
    """
    temperature = temperature if temperature is not None else config.LLM_TEMPERATURE
    max_tokens = max_tokens if max_tokens is not None else config.LLM_MAX_TOKENS

    if json_mode:
        messages = list(messages)
        messages.append(
            {
                "role": "system",
                "content": "Отвечай ТОЛЬКО валидным JSON без markdown-обёрток и пояснений.",
            }
        )

    providers = []
    if config.DEEPSEEK_API_KEY:
        providers.append(
            ("deepseek", config.DEEPSEEK_URL, config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL)
        )
    if config.GROQ_API_KEY:
        providers.append(("groq", config.GROQ_URL, config.GROQ_API_KEY, config.GROQ_MODEL))

    if not providers:
        raise LLMError("Не настроен ни один LLM-провайдер (DEEPSEEK_API_KEY / GROQ_API_KEY)")

    last_err = None
    for name, url, key, model in providers:
        for attempt in range(retries):
            try:
                content = _call_openai_compatible(
                    url, key, model, messages, temperature, max_tokens
                )
                if json_mode:
                    content = _extract_json(content)
                return content
            except Exception as e:
                last_err = e
                logger.warning(f"LLM {name} попытка {attempt + 1}: {e}")
                if attempt < retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
    raise LLMError(f"Все LLM-провайдеры недоступны: {last_err}")


def _extract_json(text):
    """Извлекает JSON из ответа LLM (устойчив к markdown-обёрткам и лишнему тексту)."""
    text = text.strip()
    # Убираем markdown-обёртки
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # Пробуем распарсить напрямую
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Ищем JSON-объект
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    # Ищем JSON-массив
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError(f"Не удалось извлечь JSON из ответа: {text[:300]}")
