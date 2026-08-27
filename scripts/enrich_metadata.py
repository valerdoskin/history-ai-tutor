#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Этап 2: Обогащение метаданных через DeepSeek.

Читает все JSON из output/, для каждого параграфа отправляет текст в LLM
и извлекает структурированные метаданные:
  - даты и события (для хронологии);
  - персоналии (имя, годы жизни, роль);
  - термины и понятия (с определениями);
  - причинно-следственные связи (причина → следствие);
  - ключевые факты для ОГЭ/ЕГЭ;
  - типовые вопросы ОГЭ/ЕГЭ по теме;
  - привязку к кодификатору ФИПИ (код темы).

Результат сохраняется в knowledge/enriched.json.

Использование:
    python scripts/enrich_metadata.py                # полный прогон
    python scripts/enrich_metadata.py --resume       # продолжить с места остановки
    python scripts/enrich_metadata.py --mock         # режим заглушки (без API)
    python scripts/enrich_metadata.py --limit 10     # обработать только 10 параграфов
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

# Добавляем корень проекта в sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# Загружаем .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(BASE_DIR, "enrich_metadata.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# Конфигурация
# ============================================================
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
ENRICHED_FILE = os.path.join(KNOWLEDGE_DIR, "enriched.json")
PROGRESS_FILE = os.path.join(KNOWLEDGE_DIR, "enrich_progress.json")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MAX_CHARS = int(os.getenv("ENRICH_MAX_CHARS", "6000"))
DELAY = float(os.getenv("ENRICH_DELAY", "0.5"))
MAX_RETRIES = int(os.getenv("ENRICH_MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("ENRICH_RETRY_DELAY", "1.0"))

# ============================================================
# Промт для LLM
# ============================================================
SYSTEM_PROMPT = """Ты — эксперт по истории России и всеобщей истории, готовишь школьников к ОГЭ и ЕГЭ.

Твоя задача — проанализировать текст параграфа из учебника и извлечь из него структурированные метаданные для базы знаний ИИ-репетитора.

Верни ТОЛЬКО валидный JSON без пояснений, в формате:
{
  "dates": [
    {"year": "1917", "event": "Октябрьская революция", "description": "краткое описание"}
  ],
  "figures": [
    {"name": "Пётр I", "years": "1672–1725", "role": "царь, реформатор", "description": "краткое описание"}
  ],
  "terms": [
    {"term": "абсолютизм", "definition": "форма правления, при которой власть монарха неограниченна"}
  ],
  "causal_links": [
    {"cause": "причина", "effect": "следствие", "description": "краткое пояснение связи"}
  ],
  "key_facts": [
    "ключевой факт для ОГЭ/ЕГЭ"
  ],
  "exam_questions": [
    {"question": "типовой вопрос ОГЭ/ЕГЭ по теме", "answer": "краткий ответ"}
  ],
  "fipi_codes": ["код темы по кодификатору ФИПИ, если определим, иначе пустой массив"]
}

Правила:
- Извлекай ТОЛЬКО то, что есть в тексте. НЕ выдумывай факты.
- Даты указывай в формате "год" (например "1917" или "1917–1922").
- Для персоналий указывай годы жизни, если они есть в тексте.
- causal_links — причинно-следственные связи, явно выраженные в тексте.
- key_facts — 3-7 самых важных фактов для экзамена.
- exam_questions — 2-4 типовых вопроса ОГЭ/ЕГЭ по теме параграфа.
- fipi_codes — коды тем по кодификатору ФИПИ (например "1.1.2"), если сможешь определить по содержанию. Если не уверен — пустой массив.
- Если какой-то раздел пуст — верни пустой массив [].
"""


def build_user_prompt(book_line, chapter_title, paragraph_title, main_question, content):
    """Формирует промт пользователя для LLM."""
    parts = []
    parts.append(f"Книга: {book_line}")
    parts.append(f"Глава: {chapter_title}")
    parts.append(f"Параграф: {paragraph_title}")
    if main_question:
        parts.append(f"Главный вопрос параграфа: {main_question}")
    parts.append("")
    parts.append("Текст параграфа:")
    parts.append(content)
    return "\n".join(parts)


# ============================================================
# HTTP-клиент для LLM
# ============================================================
def call_llm(messages):
    """Вызывает LLM (DeepSeek → Groq). Возвращает текст ответа или None."""
    import urllib.request
    import urllib.error

    providers = []
    if DEEPSEEK_API_KEY:
        providers.append(("DeepSeek", DEEPSEEK_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL))
    if GROQ_API_KEY:
        providers.append(("Groq", GROQ_URL, GROQ_API_KEY, GROQ_MODEL))

    if not providers:
        return None

    for name, url, api_key, model in providers:
        for attempt in range(MAX_RETRIES):
            try:
                payload = json.dumps({
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 4000,
                }).encode("utf-8")

                req = urllib.request.Request(url, data=payload, method="POST")
                req.add_header("Content-Type", "application/json")
                req.add_header("Authorization", f"Bearer {api_key}")

                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                logger.warning(f"{name} HTTP {e.code}: {e.read().decode('utf-8')[:200]}")
                if e.code == 429:  # rate limit
                    time.sleep(5 * (attempt + 1))
                    continue
                break
            except Exception as e:
                logger.warning(f"{name} ошибка (попытка {attempt+1}): {e}")
                time.sleep(2 * (attempt + 1))

    return None


def fix_unescaped_quotes(s):
    """Исправляет неэкранированные кавычки внутри строк JSON (когда LLM не экранирует их)."""
    result = []
    in_string = False
    escaped = False
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if escaped:
            result.append(c)
            escaped = False
            i += 1
            continue
        if c == "\\":
            result.append(c)
            escaped = True
            i += 1
            continue
        if c == '"':
            if in_string:
                # Проверяем, является ли эта кавычка закрывающей
                # Закрывающая кавычка: за ней следует , } ] : пробел или конец
                j = i + 1
                while j < n and s[j] in " \t\n\r":
                    j += 1
                if j >= n or s[j] in ",}]:":
                    in_string = False
                    result.append(c)
                else:
                    # Неэкранированная кавычка внутри строки
                    result.append('\\"')
            else:
                in_string = True
                result.append(c)
            i += 1
            continue
        result.append(c)
        i += 1
    return "".join(result)


def parse_llm_json(text):
    """Извлекает JSON из ответа LLM (устойчив к markdown-обёрткам и лишнему тексту)."""
    if not text:
        return None
    text = text.strip()
    # Убираем markdown-обёртки ```json ... ```
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Прямая попытка
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Пробуем найти JSON-объект в тексте (от первой { до последней })
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Пробуем найти JSON-массив в тексте
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Пробуем починить: убрать trailing-запятые и одинарные кавычки
    import re
    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    fixed = fixed.replace("'", '"')
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Пробуем исправить неэкранированные кавычки внутри строк
    fixed = fix_unescaped_quotes(text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    return None


# ============================================================
# Mock-режим (заглушка без API)
# ============================================================
def mock_enrich(paragraph):
    """Возвращает заглушку метаданных для тестирования без API."""
    title = paragraph.get("title", "")
    content = paragraph.get("content", "")
    key_elements = paragraph.get("key_elements", {})

    dates = []
    for d in key_elements.get("dates", []):
        dates.append({"year": d.strip(), "event": "", "description": ""})

    figures = []
    for f in key_elements.get("figures", []):
        figures.append({"name": f.strip(), "years": "", "role": "", "description": ""})

    terms = []
    for t in key_elements.get("terms", []):
        terms.append({"term": t.strip(), "definition": ""})

    return {
        "dates": dates,
        "figures": figures,
        "terms": terms,
        "causal_links": [],
        "key_facts": [f"Ключевой факт из параграфа: {title}"],
        "exam_questions": [
            {"question": f"Вопрос по теме: {title}", "answer": "Ответ из текста параграфа"}
        ],
        "fipi_codes": [],
        "_mock": True,
    }


# ============================================================
# Загрузка данных
# ============================================================
def load_all_paragraphs():
    """Загружает все параграфы из output/*.json. Возвращает список словарей."""
    import glob

    paragraphs = []
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.json")))
    for f in files:
        if f.endswith("report.json"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            logger.error(f"Не удалось прочитать {f}: {e}")
            continue

        book_id = data.get("book_id", os.path.basename(f).replace(".json", ""))
        book_line = data.get("book_line", "")
        source_file = data.get("source_file", os.path.basename(f))

        for chapter in data.get("data", []):
            chapter_title = chapter.get("title", "")
            chapter_number = chapter.get("number", "")
            for para in chapter.get("paragraphs", []):
                paragraphs.append({
                    "book_id": book_id,
                    "book_line": book_line,
                    "source_file": source_file,
                    "chapter_title": chapter_title,
                    "chapter_number": chapter_number,
                    "paragraph": para,
                })

    logger.info(f"Загружено параграфов: {len(paragraphs)}")
    return paragraphs


def paragraph_to_text(entry):
    """Собирает текст параграфа для отправки в LLM."""
    para = entry["paragraph"]
    parts = []

    title = para.get("title", "")
    if title:
        parts.append(f"Заголовок: {title}")

    main_question = para.get("main_question", "")
    if main_question:
        parts.append(f"Главный вопрос: {main_question}")

    # Разделы
    for section in para.get("sections", []):
        sec_title = section.get("title", "")
        if sec_title:
            parts.append(f"\n[{sec_title}]")
        for content in section.get("content", []):
            if content:
                parts.append(content)

    # Спецблоки
    for block_type, blocks in para.get("special_blocks", {}).items():
        if isinstance(blocks, list):
            for block in blocks:
                if isinstance(block, str) and block:
                    parts.append(f"\n[{block_type}]: {block}")
                elif isinstance(block, dict):
                    for k, v in block.items():
                        if v:
                            parts.append(f"\n[{block_type} / {k}]: {v}")

    # Синхронистическая таблица
    for row in para.get("sync_table", []):
        if isinstance(row, dict):
            parts.append(f"\n[Синхронистическая таблица]: {json.dumps(row, ensure_ascii=False)}")

    text = "\n".join(parts)
    # Ограничиваем длину
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n...[текст обрезан]"
    return text


# ============================================================
# Основная логика
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Обогащение метаданных через DeepSeek")
    parser.add_argument("--resume", action="store_true", help="Продолжить с места остановки")
    parser.add_argument("--mock", action="store_true", help="Режим заглушки (без API)")
    parser.add_argument("--limit", type=int, default=None, help="Обработать только N параграфов")
    args = parser.parse_args()

    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)

    # Проверка наличия API-ключа
    if not args.mock and not DEEPSEEK_API_KEY and not GROQ_API_KEY:
        logger.warning("Нет DEEPSEEK_API_KEY и GROQ_API_KEY. Запускаю в mock-режиме.")
        logger.warning("Для реального обогащения добавьте ключ в .env")
        args.mock = True

    # Загружаем все параграфы
    all_entries = load_all_paragraphs()
    if args.limit:
        all_entries = all_entries[:args.limit]

    # Загружаем прогресс (для --resume)
    processed = {}
    if args.resume and os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, encoding="utf-8") as fh:
                processed = json.load(fh)
            logger.info(f"Возобновление: уже обработано {len(processed)} параграфов")
        except Exception:
            processed = {}

    # Загружаем существующий результат (для --resume)
    enriched = {}
    if args.resume and os.path.exists(ENRICHED_FILE):
        try:
            with open(ENRICHED_FILE, encoding="utf-8") as fh:
                enriched = json.load(fh)
        except Exception:
            enriched = {}

    # Обрабатываем параграфы
    total = len(all_entries)
    done = 0
    errors = 0
    skipped = 0

    for i, entry in enumerate(all_entries):
        para = entry["paragraph"]
        # Ключ параграфа: book_id + chapter + title
        para_key = f"{entry['book_id']}::{entry['chapter_number']}::{para.get('title', '')}"

        # Пропускаем уже успешно обработанные (для --resume).
        # Параграфы со статусом "error" или "empty" обрабатываем заново.
        if para_key in processed and processed[para_key].get("status") == "ok":
            skipped += 1
            continue

        text = paragraph_to_text(entry)
        if not text.strip():
            logger.warning(f"[{i+1}/{total}] Пустой текст параграфа: {para_key}")
            processed[para_key] = {"status": "empty"}
            continue

        logger.info(f"[{i+1}/{total}] Обработка: {entry['book_line']} / {entry['chapter_title']} / {para.get('title', '')[:50]}")

        if args.mock:
            meta = mock_enrich(para)
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(
                    entry["book_line"], entry["chapter_title"],
                    para.get("title", ""), para.get("main_question", ""), text
                )},
            ]
            meta = None
            last_response = ""
            for attempt in range(1, MAX_RETRIES + 1):
                response = call_llm(messages)
                last_response = response
                meta = parse_llm_json(response)
                if meta is not None:
                    break
                logger.warning(f"[{i+1}/{total}] Попытка {attempt}/{MAX_RETRIES} не удалась для: {para_key}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
            if meta is None:
                logger.error(f"[{i+1}/{total}] Не удалось распарсить ответ LLM после {MAX_RETRIES} попыток для: {para_key}")
                logger.error(f"  Сырой ответ (первые 500 символов): {str(last_response)[:500]}")
                errors += 1
                processed[para_key] = {"status": "error"}
                continue

        # Сохраняем результат
        enriched[para_key] = {
            "book_id": entry["book_id"],
            "book_line": entry["book_line"],
            "source_file": entry["source_file"],
            "chapter_title": entry["chapter_title"],
            "chapter_number": entry["chapter_number"],
            "paragraph_title": para.get("title", ""),
            "paragraph_number": para.get("number", ""),
            "page_start": para.get("page_start"),
            "page_end": para.get("page_end"),
            "main_question": para.get("main_question", ""),
            "metadata": meta,
        }
        processed[para_key] = {"status": "ok"}
        done += 1

        # Сохраняем прогресс каждые 10 параграфов
        if done % 10 == 0:
            with open(PROGRESS_FILE, "w", encoding="utf-8") as fh:
                json.dump(processed, fh, ensure_ascii=False, indent=2)
            with open(ENRICHED_FILE, "w", encoding="utf-8") as fh:
                json.dump(enriched, fh, ensure_ascii=False, indent=2)
            logger.info(f"  Прогресс сохранён: {done} обработано, {errors} ошибок")

        # Задержка между запросами (чтобы не превысить лимиты API)
        if not args.mock and DELAY > 0:
            time.sleep(DELAY)

    # Финальное сохранение
    with open(PROGRESS_FILE, "w", encoding="utf-8") as fh:
        json.dump(processed, fh, ensure_ascii=False, indent=2)
    with open(ENRICHED_FILE, "w", encoding="utf-8") as fh:
        json.dump(enriched, fh, ensure_ascii=False, indent=2)

    logger.info("=" * 60)
    logger.info(f"ИТОГО: обработано {done}, пропущено {skipped}, ошибок {errors}")
    logger.info(f"Результат сохранён: {ENRICHED_FILE}")
    logger.info(f"Всего в базе: {len(enriched)} параграфов")


if __name__ == "__main__":
    main()
