"""Построение реестра вопросов по историческим источникам.

Извлекает из базы знаний (chunks.json) отрывки исторических документов
(грамоты, летописи, договоры, воспоминания, письма) и генерирует через LLM
вопросы по каждому источнику в формате ЕГЭ (работа с источником).

Результат сохраняется в knowledge/source_questions.json.

Запуск:
    python scripts/build_source_questions.py [--limit N] [--per-source M]
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import knowledge_service, llm_service

_OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge",
    "source_questions.json",
)

# Паттерны, указывающие на цитату исторического документа
_SOURCE_PATTERNS = [
    r"Из сочинения",
    r"Из грамоты",
    r"Из летописи",
    r"Из указа",
    r"Из договора",
    r"Из письма",
    r"Из воспоминаний",
    r"Из дневника",
    r"Из записок",
    r"Из документа",
    r"Из Правды",
    r"Из Декрета",
    r"Из Конституции",
    r"Из Декларации",
    r"Из Указа",
    r"Из Североатлантического",
    r"Из Варшавского",
    r"Из Концепции",
    r"Из Генерального",
    r"Из Гюльханейского",
    r"Из Лицевого",
    r"Из Сирии",
    r"Из Гельсингфорса",
    r"Из США",
    r"Из Индии",
    r"Из Москвы",
]

# Паттерны, указывающие на служебные блоки (задания, вопросы), которые не являются источниками
_NOISE_PATTERNS = [
    r"Прочитайте отрывки из исторических источников и определите",
    r"Расставьте отрывки в хронологической последовательности",
    r"Задания данного раздела выполняйте в тетрадях",
    r"Рассмотрите картину",
    r"Прочитайте поэму",
    r"Прочитайте фрагмент очерка",
    r"Работаем с ПОНЯТИЯМИ",
    r"Работаем с ХРОНОЛОГИЕЙ",
    r"Работаем с ИСтОЧНИКОМ",
    r"Используя дополнительные источники информации",
    r"Выясните, какие герои",
    r"Раскройте смысл понятия",
    r"Приведите два исторических факта",
    r"Ознакомьтесь с перечнем",
    r"Какие из приведённых памятников культуры",
]


def _extract_source_text(text):
    """Извлекает отрывок документа из текста чанка.

    Возвращает (source_text, source_title) или (None, None), если источник не найден.
    """
    # Ищем цитату документа — перебираем все паттерны и все вхождения
    for pattern in _SOURCE_PATTERNS:
        for m in re.finditer(pattern, text):
            # Определяем заголовок источника (строка с "Из ...")
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            if line_end == -1:
                line_end = len(text)
            title_line = text[line_start:line_end].strip()
            # Текст источника — от начала цитаты до конца чанка или до следующего служебного блока
            source_text = text[m.start():]
            # Обрезаем по служебным блокам
            for noise in _NOISE_PATTERNS:
                nm = re.search(noise, source_text)
                if nm:
                    source_text = source_text[:nm.start()]
                    break
            source_text = source_text.strip()
            # Отфильтровываем слишком короткие источники
            if len(source_text) < 100:
                continue
            # Отфильтровываем источники, которые начинаются с буквенных маркеров заданий
            if re.match(r"^[А-Я]\)", source_text):
                continue
            # Отфильтровываем источники, содержащие признаки заданий
            if re.search(r"Прочитайте|Охарактеризуйте|Ответьте|Выполните", source_text[:200]):
                continue
            # Отфильтровываем источники, заголовок которых начинается с буквенного маркера
            if re.match(r"^[А-Я]\)", title_line):
                continue
            # Отфильтровываем источники, заголовок которых содержит признаки заданий
            if re.search(r"Прочитайте|Охарактеризуйте|Ответьте|Выполните|Задания", title_line):
                continue
            # Отфильтровываем списки литературы (много названий книг в заголовке)
            if title_line.count("«") >= 2 and "Из " not in title_line:
                continue
            # Отфильтровываем текст учебника, начинающийся с "Из [географическое название]"
            # (не является цитатой документа)
            if re.match(r"^Из (Сирии|США|Индии|Москвы|Гельсингфорса|Канады|Египта|Персии|Китая|Японии|Англии|Франции|Германии|Италии|Испании|Португалии|Голландии|Америки|России|Петербурга|Москвы)\b", title_line):
                continue
            # Отфильтровываем источники, заголовок которых не начинается с "Из" или кавычки
            # (обрывки текста, продолжения отрывков, маркеры заданий)
            if not re.match(r"^(Из |«|\")", title_line):
                # Исключение: явные начала цитат (Но есть, Может кто, Сначала и т.д.)
                if not re.match(r"^(Но есть|Может кто|Сначала|Однако|В то же время|Помещичьи|Нашему|махали|они поплывут|Советская внешняя|фавориты|Президент РСФСР|Русские специалисты)", title_line):
                    continue
                # Для таких источников текст цитаты начинается с title_line
                # Убираем "Из ..." из начала source_text
                source_text = re.sub(r"^Из [^\n]*\n?", "", source_text)
                source_text = (title_line + "\n" + source_text).strip()
            return source_text, title_line
    return None, None


def _collect_sources():
    """Собирает источники из базы знаний."""
    chunks = knowledge_service._load_chunks()
    sources = []
    seen = set()
    for ch in chunks:
        text = ch.get("text", "")
        source_text, title = _extract_source_text(text)
        if not source_text:
            continue
        # Дедупликация по началу текста
        key = source_text[:100]
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "source_text": source_text,
            "source_title": title,
            "paragraph": str(ch.get("paragraph_title", "")).strip(),
            "chapter": str(ch.get("chapter_title", "")).strip(),
            "source_file": ch.get("source_file", ""),
            "class": knowledge_service.get_class_from_source(ch.get("source_file", "")),
        })
    return sources


def _generate_questions(source, per_source):
    """Генерирует вопросы по источнику через LLM."""
    system_prompt = (
        "Ты — составитель заданий ЕГЭ по истории по формату ФИПИ. "
        "По данному отрывку исторического источника составь вопросы в формате "
        "заданий ЕГЭ на работу с источником (задания 17-21). "
        "Вопросы должны проверять: понимание содержания источника, определение "
        "исторического периода/события, авторство/название документа, "
        "причинно-следственные связи. "
        "Верни ТОЛЬКО JSON-массив без пояснений в формате: "
        '[{"question": "...", "answer": "...", "type": "source"}]'
    )
    user_prompt = (
        f"Исторический источник:\n{source['source_text'][:2000]}\n\n"
        f"Параграф: {source['paragraph']}\n"
        f"Глава: {source['chapter']}\n"
        f"Класс: {source['class']}\n\n"
        f"Составь {per_source} вопроса по этому источнику."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        result = llm_service.call_llm(messages, json_mode=True, max_tokens=1000)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "questions" in result:
            return result["questions"]
        return []
    except Exception as e:
        print(f"  Ошибка генерации: {e}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="Максимальное число источников (0 = все)")
    parser.add_argument("--per-source", type=int, default=2,
                        help="Число вопросов на источник")
    args = parser.parse_args()

    sources = _collect_sources()
    print(f"Найдено источников: {len(sources)}")

    if args.limit:
        sources = sources[: args.limit]

    # Загружаем существующий реестр
    registry = {}
    if os.path.exists(_OUTPUT):
        try:
            registry = json.load(open(_OUTPUT, encoding="utf-8"))
        except Exception:
            registry = {}

    done = 0
    failed = 0
    t_start = time.time()

    for i, src in enumerate(sources, 1):
        key = src["source_text"][:100]
        if key in registry:
            continue
        questions = _generate_questions(src, args.per_source)
        if questions:
            registry[key] = {
                "source_text": src["source_text"],
                "source_title": src["source_title"],
                "paragraph": src["paragraph"],
                "chapter": src["chapter"],
                "source_file": src["source_file"],
                "class": src["class"],
                "questions": questions,
            }
            done += 1
        else:
            failed += 1
        if i % 5 == 0 or i == len(sources):
            elapsed = time.time() - t_start
            rate = i / elapsed if elapsed > 0 else 0
            print(
                f"[{i}/{len(sources)}] сгенерировано={done} ошибок={failed} "
                f"скорость={rate:.1f} ист/с "
                f"осталось~{(len(sources)-i)/rate/60:.1f} мин",
                flush=True,
            )

    with open(_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    total_questions = sum(len(v["questions"]) for v in registry.values())
    print(f"\nГотово: сгенерировано={done}, ошибок={failed}")
    print(f"Всего источников в реестре: {len(registry)}")
    print(f"Всего вопросов в реестре: {total_questions}")


if __name__ == "__main__":
    main()
