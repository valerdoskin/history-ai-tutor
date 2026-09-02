#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Этап 4: Расширение банка вопросов (knowledge/question_bank.json).

Генерирует новые вопросы по типам, которые ФИПИ называет самыми сложными:
- chronology (+30): расстановка событий в хронологическом порядке
- argumentation (+20): аргументы за/против точки зрения (ЕГЭ 21 / ОГЭ 6)
- cause_effect (+30): причины и следствия (ЕГЭ 18)
- comparison (+20): сравнение событий/явлений (ЕГЭ 20 / ОГЭ 23)
- culture (+30): памятники культуры (автор, год, название) на основе culture.json

Источник данных — knowledge/chunks.json (тексты учебников) и knowledge/culture.json.

Формат записи (сохраняет текущую схему question_bank.json):
{вопрос: {class, answer, type, distractors}}

Использование:
    python scripts/build_questions.py                # полный прогон
    python scripts/build_questions.py --mock         # режим заглушки (без API)
    python scripts/build_questions.py --limit 2      # генерировать только 2 батча на тип
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
        logging.FileHandler(os.path.join(BASE_DIR, "build_questions.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
CHUNKS_FILE = os.path.join(KNOWLEDGE_DIR, "chunks.json")
CULTURE_FILE = os.path.join(KNOWLEDGE_DIR, "culture.json")
QUESTION_BANK_FILE = os.path.join(KNOWLEDGE_DIR, "question_bank.json")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# Системные промпты для каждого типа
SYSTEM_PROMPTS = {
    "chronology": """Ты — эксперт по истории России и всеобщей истории, готовишь школьников к ОГЭ и ЕГЭ.

Твоя задача — составить вопросы на расстановку событий в хронологическом порядке (формат ЕГЭ 1-2 / ОГЭ 1-2).

Верни ТОЛЬКО валидный JSON-массив без пояснений. Каждый элемент массива:
{
  "question": "Расположите в хронологической последовательности исторические события: [событие А]; [событие Б]; [событие В]; [событие Г].",
  "answer": "1) [самое раннее событие]; 2) [второе]; 3) [третье]; 4) [самое позднее].",
  "class": 7,
  "distractors": []
}

Правила:
- Используй ТОЛЬКО события, упомянутые в предоставленном тексте. НЕ выдумывай даты и события.
- Вопрос должен содержать 3-4 события из одного исторического периода.
- answer — правильная хронологическая последовательность с номерами.
- class — класс, к которому относится период (5-11).
- distractor — пустой массив [].
""",
    "argumentation": """Ты — эксперт по истории России и всеобщей истории, готовишь школьников к ОГЭ и ЕГЭ.

Твоя задача — составить вопросы на аргументацию точки зрения (формат ЕГЭ 21 / ОГЭ 6): «Приведите аргументы за/против точки зрения».

Верни ТОЛЬКО валидный JSON-массив без пояснений. Каждый элемент массива:
{
  "question": "В исторической науке существует точка зрения: «[спорное утверждение]». Приведите два аргумента в подтверждение и два аргумента в опровержение этой точки зрения.",
  "answer": "Аргументы в подтверждение: 1) [факт]; 2) [факт]. Аргументы в опровержение: 1) [факт]; 2) [факт].",
  "class": 9,
  "distractors": []
}

Правила:
- Спорное утверждение должно опираться на факты из предоставленного текста.
- Каждый аргумент должен содержать конкретный исторический факт (событие, дату, имя).
- answer — эталонный ответ с 2 аргументами за и 2 аргументами против, каждый с фактом.
- class — класс, к которому относится период (5-11).
- distractor — пустой массив [].
""",
    "cause_effect": """Ты — эксперт по истории России и всеобщей истории, готовишь школьников к ОГЭ и ЕГЭ.

Твоя задача — составить вопросы на установление причин и следствий (формат ЕГЭ 18).

Верни ТОЛЬКО валидный JSON-массив без пояснений. Каждый элемент массива:
{
  "question": "Укажите причины [события/явления] и его последствия.",
  "answer": "Причины: 1) [причина]; 2) [причина]. Последствия: 1) [следствие]; 2) [следствие].",
  "class": 8,
  "distractors": []
}

Правила:
- Причины и следствия должны опираться на факты из предоставленного текста. НЕ выдумывай.
- answer — эталонный ответ с 2 причинами и 2 следствиями, каждый с фактом.
- class — класс, к которому относится период (5-11).
- distractor — пустой массив [].
""",
    "comparison": """Ты — эксперт по истории России и всеобщей истории, готовишь школьников к ОГЭ и ЕГЭ.

Твоя задача — составить вопросы на сравнение исторических событий/явлений (формат ЕГЭ 20 / ОГЭ 23).

Верни ТОЛЬКО валидный JSON-массив без пояснений. Каждый элемент массива:
{
  "question": "Сравните [явление А] и [явление Б]. Укажите не менее двух общих черт и двух различий.",
  "answer": "Общие черты: 1) [черта]; 2) [черта]. Различия: 1) [различие]; 2) [различие].",
  "class": 9,
  "distractors": []
}

Правила:
- Сравниваемые явления должны быть из предоставленного текста. НЕ выдумывай.
- answer — эталонный ответ с 2 общими чертами и 2 различиями, каждый с фактом.
- class — класс, к которому относится период (5-11).
- distractor — пустой массив [].
""",
    "culture": """Ты — эксперт по истории России и всеобщей истории, готовишь школьников к ОГЭ и ЕГЭ.

Твоя задача — составить вопросы по памятникам культуры (автор, год, название) на основе предоставленного справочника по культуре.

Верни ТОЛЬКО валидный JSON-массив без пояснений. Каждый элемент массива:
{
  "question": "Кто является автором [памятника культуры]?",
  "answer": "[имя автора]",
  "class": 7,
  "distractors": ["[неверный вариант 1]", "[неверный вариант 2]", "[неверный вариант 3]"]
}

Правила:
- Используй ТОЛЬКО записи из предоставленного справочника по культуре. НЕ выдумывай авторов, годы, названия.
- Вопросы могут быть: «Кто автор...», «В каком году создан...», «Как называется...».
- answer — правильный ответ из справочника.
- distractors — 3 правдоподобных неверных варианта (из других записей справочника или правдоподобные, но НЕ правильный).
- class — класс из записи справочника.
""",
}

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

MAX_RETRIES = int(os.getenv("QB_MAX_RETRIES", "3"))
DELAY = float(os.getenv("QB_DELAY", "0.5"))

# Сколько вопросов каждого типа нужно добавить
TARGETS = {
    "chronology": 30,
    "argumentation": 20,
    "cause_effect": 30,
    "comparison": 20,
    "culture": 30,
}

# Классы, по которым распределяем вопросы (5-11)
CLASSES = [5, 6, 7, 8, 9, 10, 11]


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


def select_chunks_for_class(chunks, cls):
    """Выбирает чанки для заданного класса."""
    return [c for c in chunks if get_class_from_source(c.get("source_file", "")) == cls]


def build_context(chunks_for_class, max_chars=6000):
    """Собирает контекст из чанков для LLM."""
    parts = []
    total = 0
    for c in chunks_for_class:
        text = c.get("text", "")
        if total + len(text) > max_chars:
            break
        parts.append(text)
        total += len(text)
    return "\n".join(parts)


def generate_batch(qtype, chunks, culture_records, cls, mock=False):
    """Генерирует батч вопросов одного типа для одного класса."""
    if mock:
        return []

    if qtype == "culture":
        cls_records = [r for r in culture_records if r.get("class") == cls]
        if not cls_records:
            return []
        sample = cls_records[:40]
        context = json.dumps(sample, ensure_ascii=False, indent=1)[:6000]
        user_prompt = (
            f"Класс: {cls}\n\n"
            f"Справочник по культуре (записи для этого класса):\n{context}\n\n"
            f"Составь 5 вопросов по памятникам культуры этого класса."
        )
    else:
        chunks_for_class = select_chunks_for_class(chunks, cls)
        if not chunks_for_class:
            return []
        context = build_context(chunks_for_class)
        user_prompt = (
            f"Класс: {cls}\n\n"
            f"Текст учебника:\n{context}\n\n"
            f"Составь 5 вопросов типа '{qtype}' по этому тексту."
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPTS[qtype]},
        {"role": "user", "content": user_prompt},
    ]
    resp = call_llm(messages)
    if not resp:
        logger.warning(f"LLM не ответил для типа {qtype}, класс {cls}")
        return []
    parsed = extract_json(resp)
    if parsed is None:
        logger.warning(f"Не удалось распарсить ответ для типа {qtype}, класс {cls}")
        return []
    if isinstance(parsed, dict):
        parsed = parsed.get("questions", []) or parsed.get("records", [])
    if not isinstance(parsed, list):
        return []

    result = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        question = item.get("question") or item.get("name")
        answer = item.get("answer")
        if not question or not answer:
            continue
        distractors = item.get("distractors", [])
        if not isinstance(distractors, list):
            distractors = []
        result.append({
            "question": question,
            "answer": answer,
            "class": item.get("class") or cls,
            "type": qtype,
            "distractors": [d for d in distractors if d and d != answer][:3],
        })
    time.sleep(DELAY)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="режим заглушки (без API)")
    parser.add_argument("--limit", type=int, default=0, help="генерировать только N батчей на тип")
    args = parser.parse_args()

    chunks = load_json(CHUNKS_FILE)
    culture_records = load_json(CULTURE_FILE)
    bank = load_json(QUESTION_BANK_FILE)

    from collections import Counter
    current = Counter(v.get("type") for v in bank.values())
    logger.info(f"Текущее количество вопросов в банке: {len(bank)}")
    logger.info(f"По типам: {dict(current)}")

    added_total = 0
    for qtype, target in TARGETS.items():
        need = target
        logger.info(f"=== Тип: {qtype}, нужно добавить: {need} ===")
        added_for_type = 0
        batch_count = 0
        cls_idx = 0
        while added_for_type < need:
            if args.limit and batch_count >= args.limit:
                break
            cls = CLASSES[cls_idx % len(CLASSES)]
            cls_idx += 1
            batch_count += 1
            logger.info(f"  Генерация батча для класса {cls}...")
            new_qs = generate_batch(qtype, chunks, culture_records, cls, mock=args.mock)
            for q in new_qs:
                question = q["question"]
                if question in bank:
                    continue
                bank[question] = {
                    "class": q["class"],
                    "answer": q["answer"],
                    "type": q["type"],
                    "distractors": q["distractors"],
                }
                added_for_type += 1
                added_total += 1
                if added_for_type >= need:
                    break
            logger.info(f"    Добавлено для типа {qtype}: {added_for_type}/{need}")
            if batch_count > 60:
                logger.warning(f"Превышен лимит батчей для типа {qtype}, останавливаемся")
                break

        with open(QUESTION_BANK_FILE, "w", encoding="utf-8") as f:
            json.dump(bank, f, ensure_ascii=False, indent=2)
        logger.info(f"Сохранено. Итого добавлено для типа {qtype}: {added_for_type}")

    logger.info(f"Готово. Всего добавлено вопросов: {added_total}")
    logger.info(f"Итоговое количество вопросов в банке: {len(bank)}")


if __name__ == "__main__":
    main()

