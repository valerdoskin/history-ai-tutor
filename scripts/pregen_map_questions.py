#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Предварительная генерация map-вопросов через LLM.

Для каждой записи maps.json, у которой есть поле image:
1. Находит текст параграфа учебника по source_chunk_id (собирает все чанки
   параграфа из chunks.json).
2. Генерирует вопрос через LLM на основе текста параграфа + описания карты.
3. Сохраняет вопрос в question_bank.json с полем image.

Ключевой принцип: вопрос должен соответствовать описанию параграфа учебника,
потому что карта привязана к параграфу, и в нём описывается то, что на ней
показано.

Использование:
    python scripts/pregen_map_questions.py                # полный прогон
    python scripts/pregen_map_questions.py --mock         # режим заглушки (без API)
    python scripts/pregen_map_questions.py --limit 1      # только 1 запись
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
        logging.FileHandler(os.path.join(BASE_DIR, "pregen_map_questions.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
MAPS_FILE = os.path.join(KNOWLEDGE_DIR, "maps.json")
CHUNKS_FILE = os.path.join(KNOWLEDGE_DIR, "chunks.json")
QUESTION_BANK_FILE = os.path.join(KNOWLEDGE_DIR, "question_bank.json")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MAX_RETRIES = int(os.getenv("QB_MAX_RETRIES", "3"))
DELAY = float(os.getenv("QB_DELAY", "0.5"))

SYSTEM_PROMPT = """Ты — эксперт по истории России и всеобщей истории, готовишь школьников к ОГЭ и ЕГЭ.

Твоя задача — составить вопрос по исторической карте. Карта привязана к параграфу учебника, и в этом параграфе описывается то, что происходит на карте. Вопрос должен опираться на текст параграфа.

Верни ТОЛЬКО валидный JSON-объект без пояснений:
{
  "question": "Рассмотрите историческую карту. [вопрос о событии/походе/территориальных изменениях, показанных на карте]",
  "answer": "[правильный ответ — название события/похода/явления]",
  "distractors": ["[неверный вариант 1]", "[неверный вариант 2]", "[неверный вариант 3]"]
}

Правила:
- Вопрос должен быть составлен так, чтобы ученик, глядя на карту, мог ответить на него.
- answer — правильный ответ, который соответствует названию карты и описанию в параграфе.
- distractors — 3 правдоподобных неверных варианта (другие исторические события/походы того же периода, НЕ правильный).
- Используй ТОЛЬКО факты из предоставленного текста параграфа и описания карты. НЕ выдумывай.
"""


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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
                    "temperature": 0.4,
                    "max_tokens": 2000,
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
    """Извлекает JSON-объект из ответа LLM."""
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
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def get_paragraph_text(chunks, source_chunk_id, max_chars=6000):
    """Собирает текст параграфа по source_chunk_id.

    Находит чанк по id, затем собирает все чанки с тем же paragraph_title
    и source_file (весь параграф).
    """
    target = None
    for c in chunks:
        if c.get("id") == source_chunk_id:
            target = c
            break
    if not target:
        return None
    paragraph_title = target.get("paragraph_title")
    source_file = target.get("source_file")
    texts = []
    total = 0
    for c in chunks:
        if c.get("paragraph_title") == paragraph_title and c.get("source_file") == source_file:
            t = c.get("text", "")
            if total + len(t) > max_chars:
                break
            texts.append(t)
            total += len(t)
    return "\n".join(texts)


def generate_map_question(record, paragraph_text, mock=False):
    """Генерирует map-вопрос через LLM для одной записи maps.json."""
    if mock:
        return {
            "question": f"Рассмотрите историческую карту. Какое событие показано на карте? (mock: {record['name']})",
            "answer": record["name"],
            "distractors": ["Неверный вариант 1", "Неверный вариант 2", "Неверный вариант 3"],
        }

    name = record.get("name", "")
    description = record.get("description", "")
    key_objects = record.get("key_objects", [])
    cls = record.get("class")

    user_prompt = (
        f"Название карты: {name}\n"
        f"Класс: {cls}\n\n"
        f"Описание карты:\n{description}\n\n"
        f"Ключевые объекты на карте: {', '.join(key_objects) if key_objects else '—'}\n\n"
        f"Текст параграфа учебника (описывает то, что показано на карте):\n{paragraph_text}\n\n"
        f"Составь вопрос по этой карте."
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    resp = call_llm(messages)
    if not resp:
        logger.warning(f"LLM не ответил для карты: {name}")
        return None
    parsed = extract_json(resp)
    if parsed is None:
        logger.warning(f"Не удалось распарсить ответ для карты: {name}")
        return None
    question = parsed.get("question")
    answer = parsed.get("answer")
    distractors = parsed.get("distractors", [])
    if not question or not answer:
        logger.warning(f"Неполный ответ для карты: {name}")
        return None
    if not isinstance(distractors, list):
        distractors = []
    return {
        "question": question,
        "answer": answer,
        "distractors": [d for d in distractors if d and d != answer][:3],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="режим заглушки (без API)")
    parser.add_argument("--limit", type=int, default=0, help="обработать только N записей")
    args = parser.parse_args()

    maps = load_json(MAPS_FILE)
    chunks = load_json(CHUNKS_FILE)
    bank = load_json(QUESTION_BANK_FILE)

    # Записи с изображением
    records_with_image = [m for m in maps if m.get("image")]
    logger.info(f"Всего записей в maps.json: {len(maps)}")
    logger.info(f"Записей с изображением: {len(records_with_image)}")

    if args.limit:
        records_with_image = records_with_image[:args.limit]

    added = 0
    for record in records_with_image:
        name = record.get("name", "")
        image = record.get("image", "")
        source_chunk_id = record.get("source_chunk_id", "")
        cls = record.get("class")

        logger.info(f"=== Обработка карты: {name} (класс {cls}) ===")

        # Получить текст параграфа
        paragraph_text = get_paragraph_text(chunks, source_chunk_id)
        if not paragraph_text:
            logger.warning(f"  Не найден текст параграфа для source_chunk_id: {source_chunk_id}")
            continue
        logger.info(f"  Текст параграфа: {len(paragraph_text)} символов")

        # Сгенерировать вопрос
        result = generate_map_question(record, paragraph_text, mock=args.mock)
        if not result:
            logger.warning(f"  Не удалось сгенерировать вопрос для карты: {name}")
            continue

        question = result["question"]
        answer = result["answer"]
        distractors = result["distractors"]

        # Проверить, что вопрос ещё не в банке
        if question in bank:
            logger.info(f"  Вопрос уже есть в банке, пропускаем")
            continue

        # Сохранить в банк
        bank[question] = {
            "class": cls,
            "answer": answer,
            "type": "map",
            "distractors": distractors,
            "image": image,
        }
        added += 1
        logger.info(f"  Добавлен вопрос: {question[:100]}...")
        logger.info(f"  Ответ: {answer[:100]}")
        logger.info(f"  Дистракторы: {distractors}")

        # Сохранять после каждой записи (чтобы не потерять при сбое)
        with open(QUESTION_BANK_FILE, "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False, indent=2)

        time.sleep(DELAY)

    logger.info(f"Готово. Добавлено вопросов: {added}")
    logger.info(f"Итоговое количество вопросов в банке: {len(bank)}")


if __name__ == "__main__":
    main()
