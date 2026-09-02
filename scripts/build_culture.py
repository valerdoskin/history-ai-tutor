#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Этап 2: Создание справочника по культуре (knowledge/culture.json).

Извлекает структурированные записи о памятниках культуры России и мира
из текстов учебников (knowledge/chunks.json) через LLM.

Структура записи:
{
  "name": "Успенский собор Московского Кремля",
  "type": "architecture",          # architecture|painting|sculpture|literature|music|science
  "author": "Аристотель Фиораванти",
  "year": "1475-1479",
  "period": "Россия в XVI в.",
  "class": 7,
  "fipi_codes": ["2.1"],
  "description": "краткое описание",
  "source_chunk_id": "id чанка в chunks.json"
}

Использование:
    python scripts/build_culture.py                # полный прогон
    python scripts/build_culture.py --resume       # продолжить с места остановки
    python scripts/build_culture.py --mock         # режим заглушки (без API)
    python scripts/build_culture.py --limit 5      # обработать только 5 параграфов
"""

import argparse
import json
import logging
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

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
        logging.FileHandler(os.path.join(BASE_DIR, "build_culture.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
CHUNKS_FILE = os.path.join(KNOWLEDGE_DIR, "chunks.json")
CULTURE_FILE = os.path.join(KNOWLEDGE_DIR, "culture.json")
PROGRESS_FILE = os.path.join(KNOWLEDGE_DIR, "culture_progress.json")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MAX_CHARS = int(os.getenv("CULTURE_MAX_CHARS", "7000"))
DELAY = float(os.getenv("CULTURE_DELAY", "0.5"))
MAX_RETRIES = int(os.getenv("CULTURE_MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("CULTURE_RETRY_DELAY", "1.0"))

# Ключевые слова для определения культурных параграфов
CULTURE_KEYWORDS = [
    "культур", "искусств", "живопис", "архитектур", "литератур", "музык",
    "наук", "образован", "просвещ", "театр", "иконопис", "летопис",
    "зодчеств", "храм", "собор", "памятник", "скульптур", "живопись",
]

SYSTEM_PROMPT = """Ты — эксперт по истории России и всеобщей истории, готовишь школьников к ОГЭ и ЕГЭ.

Твоя задача — проанализировать текст параграфа из учебника и извлечь из него структурированные записи о памятниках культуры (архитектура, живопись, скульптура, литература, музыка, наука).

Верни ТОЛЬКО валидный JSON-массив без пояснений. Каждый элемент массива:
{
  "name": "название памятника/произведения/объекта",
  "type": "architecture|painting|sculpture|literature|music|science",
  "author": "автор/создатель (если есть в тексте, иначе пустая строка)",
  "year": "год или период создания (если есть в тексте, иначе пустая строка)",
  "period": "исторический период (например 'Россия в XVI в.')",
  "class": 7,
  "fipi_codes": [],
  "description": "краткое описание (1-2 предложения из текста)",
  "source_chunk_id": ""
}

Правила:
- Извлекай ТОЛЬКО то, что есть в тексте. НЕ выдумывай факты, авторов, годы.
- type: architecture (здания, храмы, соборы, дворцы), painting (иконы, картины, живопись),
  sculpture (памятники, скульптуры), literature (литературные произведения, писатели),
  music (композиторы, музыкальные произведения), science (учёные, научные открытия).
- Для литературы и науки: name — это произведение или имя деятеля культуры/науки.
- author — автор произведения или создатель памятника.
- year — год создания/написания, если указан в тексте.
- period — исторический период, к которому относится памятник.
- class — класс, в котором изучается (5-11).
- description — краткое описание на основе текста.
- Если в тексте нет значимых памятников культуры — верни пустой массив [].
"""


def get_class_from_source(source_file):
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
    if "11kl" in s or "11_kl" in s or "vseobschaya_11" in s:
        return 11
    return None


def is_culture_paragraph(chapter_title, paragraph_title):
    text = ((chapter_title or "") + " " + (paragraph_title or "")).lower()
    return any(kw in text for kw in CULTURE_KEYWORDS)


def load_chunks():
    with open(CHUNKS_FILE, encoding="utf-8") as f:
        return json.load(f)


def group_culture_paragraphs(chunks):
    """Группирует чанки по параграфам культуры."""
    from collections import OrderedDict
    paras = OrderedDict()
    for c in chunks:
        if not is_culture_paragraph(c.get("chapter_title"), c.get("paragraph_title")):
            continue
        key = (c.get("book_id"), c.get("chapter_title"), c.get("paragraph_title"))
        if key not in paras:
            paras[key] = []
        paras[key].append(c)
    return paras


def build_paragraph_text(chunks_of_para):
    """Собирает полный текст параграфа из чанков (по порядку)."""
    chunks_of_para = sorted(chunks_of_para, key=lambda c: c.get("chunk_index", 0))
    parts = []
    for c in chunks_of_para:
        text = c.get("text", "")
        # Убираем служебные строки в начале (главный вопрос, термины, персоналии)
        parts.append(text)
    return "\n".join(parts)


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
                    "temperature": 0.2,
                    "max_tokens": 4000,
                }).encode("utf-8")

                req = urllib.request.Request(url, data=payload, method="POST")
                req.add_header("Content-Type", "application/json")
                req.add_header("Authorization", f"Bearer {api_key}")

                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                logger.warning(f"{name} HTTP {e.code}: {e.read().decode('utf-8')[:200]}")
                if e.code == 429:
                    time.sleep(5 * (attempt + 1))
                    continue
                break
            except Exception as e:
                logger.warning(f"{name} ошибка (попытка {attempt+1}): {e}")
                time.sleep(2 * (attempt + 1))
    return None


def extract_json(text):
    """Извлекает JSON-массив из ответа LLM."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def process_paragraph(key, chunks_of_para, mock=False):
    """Обрабатывает один параграф, возвращает список culture-записей."""
    book_id, chapter_title, paragraph_title = key
    cls = get_class_from_source(chunks_of_para[0].get("source_file", ""))
    full_text = build_paragraph_text(chunks_of_para)

    if mock:
        return []

    # Разбиваем текст на части, если он слишком длинный
    records = []
    text_parts = []
    current = ""
    for line in full_text.split("\n"):
        if len(current) + len(line) + 1 > MAX_CHARS:
            text_parts.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        text_parts.append(current)

    for part in text_parts:
        user_prompt = (
            f"Книга: {chunks_of_para[0].get('book_line', '')}\n"
            f"Глава: {chapter_title}\n"
            f"Параграф: {paragraph_title}\n"
            f"Класс: {cls}\n\n"
            f"Текст:\n{part}"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        resp = call_llm(messages)
        if not resp:
            logger.warning(f"LLM не ответил для параграфа: {paragraph_title}")
            continue
        parsed = extract_json(resp)
        if parsed is None:
            logger.warning(f"Не удалось распарсить ответ для параграфа: {paragraph_title}")
            continue
        if isinstance(parsed, dict):
            parsed = parsed.get("records", [])
        if isinstance(parsed, list):
            for rec in parsed:
                if isinstance(rec, dict) and rec.get("name"):
                    rec["class"] = cls
                    rec["source_chunk_id"] = chunks_of_para[0].get("id", "")
                    records.append(rec)
        time.sleep(DELAY)

    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="продолжить с места остановки")
    parser.add_argument("--mock", action="store_true", help="режим заглушки (без API)")
    parser.add_argument("--limit", type=int, default=0, help="обработать только N параграфов")
    args = parser.parse_args()

    chunks = load_chunks()
    paras = group_culture_paragraphs(chunks)
    logger.info(f"Найдено культурных параграфов: {len(paras)}")

    # Загружаем прогресс
    done_keys = set()
    if args.resume and os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            done_keys = set(tuple(k) for k in json.load(f))
        logger.info(f"Пропускаем уже обработанные: {len(done_keys)}")

    all_records = []
    if os.path.exists(CULTURE_FILE):
        try:
            with open(CULTURE_FILE, encoding="utf-8") as f:
                all_records = json.load(f)
        except Exception:
            all_records = []

    processed = 0
    for key, chunks_of_para in paras.items():
        if key in done_keys:
            continue
        if args.limit and processed >= args.limit:
            break
        logger.info(f"Обработка: {key[1]} / {key[2]}")
        records = process_paragraph(key, chunks_of_para, mock=args.mock)
        all_records.extend(records)
        done_keys.add(key)
        processed += 1

        # Сохраняем прогресс и результаты
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump([list(k) for k in done_keys], f, ensure_ascii=False)
        with open(CULTURE_FILE, "w", encoding="utf-8") as f:
            json.dump(all_records, f, ensure_ascii=False, indent=2)

        logger.info(f"  -> получено записей: {len(records)}, всего: {len(all_records)}")

    # Дедупликация по name
    seen = {}
    for rec in all_records:
        name = rec.get("name", "").strip().lower()
        if name and name not in seen:
            seen[name] = rec
    deduped = list(seen.values())
    with open(CULTURE_FILE, "w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    logger.info(f"Готово. Всего записей (до дедупликации): {len(all_records)}, после: {len(deduped)}")


if __name__ == "__main__":
    main()
