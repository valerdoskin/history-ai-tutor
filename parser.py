# -*- coding: utf-8 -*-
"""
Парсер учебников истории (PDF → структурированный JSON).

Извлекает из PDF-учебника:
  - главы и параграфы (§) с номерами страниц;
  - главные вопросы параграфов;
  - разделы внутри параграфов;
  - специальные блоки (исторический портрет, свидетельство эпохи,
    работа с хронологией/источником/понятиями, подведём итоги,
    вопросы и задания, дополнительные материалы, итоги главы и т.д.);
  - ключевые элементы по форматированию шрифта:
      * даты — полужирный шрифт;
      * термины — курсив;
      * персоналии — полужирный курсив.

Важно: текст НЕ сокращается и НЕ перефразируется — всё содержимое
сохраняется в исходном виде.

Использование:
    python parser.py <pdf_path> <config_path> <output_path>
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pdfplumber

# ---------------------------------------------------------------------------
# Настройка логирования
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("history_parser")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def load_config(config_path: str) -> Dict[str, Any]:
    """Загружает JSON-конфигурацию парсера."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_bold(font_name: str) -> bool:
    """Определяет, является ли шрифт полужирным (по имени)."""
    lower = font_name.lower()
    return ("bold" in lower or "black" in lower) and "italic" not in lower


def is_italic(font_name: str) -> bool:
    """Определяет, является ли шрифт курсивным (по имени)."""
    lower = font_name.lower()
    return "italic" in lower or "oblique" in lower


def is_bold_italic(font_name: str) -> bool:
    """Определяет, является ли шрифт полужирным курсивом (по имени)."""
    lower = font_name.lower()
    return ("bold" in lower or "black" in lower) and ("italic" in lower or "oblique" in lower)


def is_header_font(font_name: str, header_fonts: List[str]) -> bool:
    """Определяет, относится ли шрифт к заголовочным (Bloc и т.п.)."""
    lower = font_name.lower()
    for hf in header_fonts:
        if hf.lower() in lower:
            return True
    return False


def group_words_into_lines(words: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """
    Группирует слова в строки по вертикальной координате (top).

    Слова, у которых разница по top не превышает порога, считаются
    принадлежащими одной строке.
    """
    if not words:
        return []

    # Сортируем слова по вертикали, затем по горизонтали
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))

    lines: List[List[Dict[str, Any]]] = []
    current_line: List[Dict[str, Any]] = []
    current_top: Optional[float] = None

    for word in sorted_words:
        top = word["top"]
        if current_top is None or abs(top - current_top) <= 2.0:
            # Слово принадлежит текущей строке
            current_line.append(word)
            if current_top is None:
                current_top = top
        else:
            # Начинаем новую строку
            lines.append(current_line)
            current_line = [word]
            current_top = top

    if current_line:
        lines.append(current_line)

    return lines


# Символы-артефакты, которые нужно удалять из текста (private use area)
# \uf401 — артефакт извлечения из PDF-шрифтов (лишний символ)
ARTIFACT_CHARS = {"\uf401"}


def clean_text(text: str) -> str:
    """Удаляет символы-артефакты из текста."""
    if not text:
        return text
    for ch in ARTIFACT_CHARS:
        text = text.replace(ch, "")
    return text


def line_to_text(line: List[Dict[str, Any]]) -> str:
    """Собирает текст строки из слов, отсортированных по горизонтали."""
    sorted_line = sorted(line, key=lambda w: w["x0"])
    return clean_text(" ".join(w["text"] for w in sorted_line).strip())


def line_formatting(line: List[Dict[str, Any]], header_fonts: List[str]) -> Dict[str, bool]:
    """
    Определяет форматирование строки по преобладающему шрифту слов.

    Возвращает словарь с флагами: is_bold, is_italic, is_bold_italic, is_header.
    """
    if not line:
        return {"is_bold": False, "is_italic": False, "is_bold_italic": False, "is_header": False}

    bold_count = sum(1 for w in line if is_bold(w["fontname"]))
    italic_count = sum(1 for w in line if is_italic(w["fontname"]))
    bold_italic_count = sum(1 for w in line if is_bold_italic(w["fontname"]))
    header_count = sum(1 for w in line if is_header_font(w["fontname"], header_fonts))
    total = len(line)

    return {
        "is_bold": bold_count > total / 2,
        "is_italic": italic_count > total / 2,
        "is_bold_italic": bold_italic_count > total / 2,
        "is_header": header_count > total / 2,
    }


def split_bold_part(line: List[Dict[str, Any]]) -> str:
    """
    Возвращает полужирную часть строки (заголовок раздела).

    Собирает слова, набранные полужирным шрифтом, до первого
    обычного слова.
    """
    if not line:
        return ""

    sorted_line = sorted(line, key=lambda w: w["x0"])

    bold_words: List[Dict[str, Any]] = []
    for w in sorted_line:
        if is_bold(w["fontname"]) or is_bold_italic(w["fontname"]):
            bold_words.append(w)
        else:
            break

    return clean_text(" ".join(w["text"] for w in bold_words).strip())


def split_regular_part(line: List[Dict[str, Any]]) -> str:
    """
    Возвращает обычную (не полужирную) часть строки.

    Собирает слова, набранные обычным шрифтом, после полужирной
    части строки (заголовка раздела).
    """
    if not line:
        return ""

    sorted_line = sorted(line, key=lambda w: w["x0"])

    regular_words: List[Dict[str, Any]] = []
    found_regular = False
    for w in sorted_line:
        if is_bold(w["fontname"]) or is_bold_italic(w["fontname"]):
            if found_regular:
                regular_words.append(w)
        else:
            found_regular = True
            regular_words.append(w)

    if not found_regular:
        return ""

    return clean_text(" ".join(w["text"] for w in regular_words).strip())


def is_noise_line(text: str, noise_patterns: List[str]) -> bool:
    """Проверяет, является ли строка «шумом» (номера страниц, колонтитулы)."""
    for pattern in noise_patterns:
        if re.match(pattern, text):
            return True
    return False


def is_footer_line(text: str, footer_patterns: List[str]) -> bool:
    """Проверяет, является ли строка колонтитулом (служебной информацией)."""
    for pattern in footer_patterns:
        if re.match(pattern, text):
            return True
    return False


# ---------------------------------------------------------------------------
# Регулярные выражения для ключевых элементов
# ---------------------------------------------------------------------------
# Даты: 911 г., 945—964, VII в., 1-м тыс. н. э., 560-е гг., 862, 988 г.
DATE_PATTERNS = [
    r"\d{1,4}\s*гг?\.?",                            # 911 г., 911 гг.
    r"\d{1,4}\s*[–—-]\s*\d{1,4}\s*гг?\.?",        # 945—964
    r"[IVXLC]+\s*вв?\.?",                            # VII в., VII вв.
    r"[IVXLC]+\s*[–—-]\s*[IVXLC]+\s*вв?\.?",        # IV—VI вв.
    r"\d+\s*[–—-]\s*\d+\s*тыс\.\s*н\.\s*э\.?",  # 1-м тыс. н. э.
    r"\d+\s*тыс\.\s*н\.\s*э\.?",                  # 1 тыс. н. э.
    r"\d+\s*[–—-]\s*\d+\s*вв?\.?",                # VIII—IX вв.
    r"\d{1,4}\s*г\.\s*до\s*н\.\s*э\.?",          # 476 г. до н. э.
    r"\d{1,4}\s*[–—-]\s*\d{1,4}\s*гг?\.\s*до\s*н\.\s*э\.?",
    r"\d{1,4}\s*г\.\s*н\.\s*э\.?",                # 988 г. н. э.
    r"\d{1,4}\s*[–—-]\s*\d{1,4}\s*гг?\.\s*н\.\s*э\.?",
    r"\d{1,4}\s*г\.",                               # 911 г.
    r"\d{1,4}\s*гг\.",                              # 911 гг.
    r"\d{1,4}\s*[–—-]\s*\d{1,4}\s*гг?\.",          # 945—964
]

# Собираем единый паттерн для поиска дат в тексте
DATE_RE = re.compile("|".join(DATE_PATTERNS))


def extract_dates(text: str) -> List[str]:
    """Извлекает даты из текста (уникальные, в порядке появления)."""
    dates: List[str] = []
    for match in DATE_RE.finditer(text):
        date = match.group(0).strip()
        if date not in dates:
            dates.append(date)
    return dates


# Слова, характерные для подписей к иллюстрациям (не являются терминами)
CAPTION_WORDS = {
    "художник", "рисунок", "фото", "фотография", "икона", "гравюра",
    "миниатюра", "реконструкция", "музей", "общий", "вид", "рельеф",
    "здании", "фрагмент", "памятник", "картина", "портрет", "скульптура",
    "мозаика", "фреска", "барельеф", "статуя", "монета", "печать",
    "рукопись", "летопись", "свиток", "карта", "схема", "диаграмма",
    "государственный", "русский", "третьяковская", "галерея", "эрмитаж",
    "севастополь", "москва", "новгород", "киев", "петербург",
}


def extract_terms_from_words(words: List[Dict[str, Any]]) -> List[str]:
    """
    Извлекает термины (курсивные слова) из списка слов страницы.

    Термины — слова, набранные курсивом (но не полужирным курсивом,
    который используется для персоналий). Слова из подписей к
    иллюстрациям отфильтровываются.
    """
    terms: List[str] = []
    for w in words:
        if is_italic(w["fontname"]) and not is_bold_italic(w["fontname"]):
            text = clean_text(w["text"]).strip(".,;:!?()«»\"")
            if len(text) > 2 and text not in terms:
                # Пропускаем слова из подписей к иллюстрациям
                if text.lower() in CAPTION_WORDS:
                    continue
                terms.append(text)
    return terms


def extract_figures_from_words(words: List[Dict[str, Any]]) -> List[str]:
    """
    Извлекает персоналии (полужирный курсив) из списка слов страницы.

    Персоналии — слова, набранные полужирным курсивом.
    """
    figures: List[str] = []
    for w in words:
        if is_bold_italic(w["fontname"]):
            text = clean_text(w["text"]).strip(".,;:!?()«»\"")
            if len(text) > 2 and text not in figures:
                figures.append(text)
    return figures


# ---------------------------------------------------------------------------
# Основная логика парсинга
# ---------------------------------------------------------------------------
def new_paragraph() -> Dict[str, Any]:
    """Создаёт пустую структуру параграфа."""
    return {
        "title": "",
        "number": "",
        "page_start": None,
        "page_end": None,
        "main_question": "",
        "terms": [],
        "sync_table": [],
        "sections": [],
        "special_blocks": {},
        "key_elements": {"dates": [], "terms": [], "figures": []},
        "content": [],
    }


def new_section() -> Dict[str, Any]:
    """Создаёт пустую структуру раздела параграфа."""
    return {
        "number": "",
        "title": "",
        "content": [],
    }


def detect_special_block(line: str, special_blocks: Dict[str, str]) -> Optional[str]:
    """
    Определяет, является ли строка заголовком специального блока.

    Возвращает ключ блока (например, "historical_portrait") или None.
    """
    line_lower = line.lower()
    for key, marker in special_blocks.items():
        if marker.lower() in line_lower:
            return key
    return None


def parse_page(
    page: Any,
    page_num: int,
    config: Dict[str, Any],
    chapters: List[Dict[str, Any]],
) -> None:
    """
    Обрабатывает одну страницу PDF: извлекает строки с форматированием
    и распределяет их по главам, параграфам, разделам и спецблокам.
    """
    structure = config["structure"]
    special_blocks = config["special_blocks"]
    header_fonts = config["fonts"]["headers"]
    noise_patterns = config["noise_patterns"]
    footer_patterns = config["footer_patterns"]

    # Извлекаем слова с информацией о шрифте
    words = page.extract_words(extra_attrs=["fontname", "size"])
    if not words:
        return

    # Группируем слова в строки
    lines = group_words_into_lines(words)

    # Текущий контекст (глава, параграф, раздел, спецблок)
    current_chapter = chapters[-1] if chapters else None
    current_paragraph = current_chapter["paragraphs"][-1] if current_chapter and current_chapter["paragraphs"] else None
    current_section = current_paragraph["sections"][-1] if current_paragraph and current_paragraph["sections"] else None
    current_block = None  # ключ текущего спецблока

    # Флаг: идёт ли сбор заголовка главы (многострочный заголовок)
    collecting_chapter_title = False

    for line_words in lines:
        text = line_to_text(line_words)
        if not text:
            continue

        # Пропускаем «шум» и колонтитулы
        if is_noise_line(text, noise_patterns) or is_footer_line(text, footer_patterns):
            continue

        fmt = line_formatting(line_words, header_fonts)

        # 1. Проверка на заголовок главы
        ch_match = re.match(structure["chapter"], text)
        if ch_match:
            chapter = {
                "title": text,
                "number": "",
                "page_start": page_num,
                "page_end": None,
                "paragraphs": [],
            }
            chapters.append(chapter)
            current_chapter = chapter
            current_paragraph = None
            current_section = None
            current_block = None
            collecting_chapter_title = True
            continue

        # 1.1. Продолжение заголовка главы (многострочный заголовок)
        if collecting_chapter_title and current_chapter:
            # Если строка — римская цифра (номер главы), сохраняем её
            roman_match = re.match(r"^\s*([IVXLC]+)\s*$", text)
            if roman_match and fmt["is_bold"]:
                current_chapter["number"] = roman_match.group(1)
                collecting_chapter_title = False
                continue
            # Иначе — это продолжение заголовка главы
            current_chapter["title"] += " " + text
            continue

        if len(text) < 2:
            continue

        # 2. Проверка на заголовок параграфа (§)
        para_match = re.match(structure["paragraph"], text)
        if para_match and current_chapter:
            para = new_paragraph()
            para["title"] = text
            para["number"] = para_match.group(1)
            para["page_start"] = page_num
            current_chapter["paragraphs"].append(para)
            current_paragraph = para
            current_section = None
            current_block = None
            continue

        # 3. Проверка на специальный блок
        block_key = detect_special_block(text, special_blocks)
        if block_key and current_paragraph:
            if block_key not in current_paragraph["special_blocks"]:
                current_paragraph["special_blocks"][block_key] = []
            current_paragraph["special_blocks"][block_key].append({
                "header": text,
                "content": [],
            })
            current_block = block_key
            current_section = None
            continue

        # 4. Проверка на главный вопрос параграфа
        if current_paragraph and current_paragraph["main_question"] == "":
            mq_match = re.match(structure["main_question"], text)
            if mq_match:
                current_paragraph["main_question"] = mq_match.group(1)
                continue

        # 5. Проверка на раздел (нумерованный заголовок)
        if current_paragraph and current_block is None:
            sec_match = re.match(structure["section"], text)
            if sec_match and fmt["is_bold"]:
                section = new_section()
                section["number"] = sec_match.group(1)

                # Заголовок раздела — только полужирная часть строки
                bold_part = split_bold_part(line_words)
                if bold_part:
                    # Убираем номер из заголовка
                    section["title"] = re.sub(r"^\s*\d+\s+", "", bold_part)
                else:
                    section["title"] = sec_match.group(2)

                current_paragraph["sections"].append(section)
                current_section = section

                # Если после заголовка на той же строке есть обычный текст
                # (не полужирный), добавляем его в содержимое раздела
                regular_part = split_regular_part(line_words)
                if regular_part:
                    current_section["content"].append(regular_part)
                continue

        # 6. Проверка на синхронистическую таблицу
        if current_paragraph and re.search(structure["sync_table"], text):
            current_paragraph["sync_table"].append(text)
            continue

        # 7. Обычный текст — добавляем в текущий контекст
        if current_block and current_paragraph:
            # Текст внутри спецблока
            current_paragraph["special_blocks"][current_block][-1]["content"].append(text)
        elif current_section:
            current_section["content"].append(text)
        elif current_paragraph:
            current_paragraph["content"].append(text)

    # Обновляем page_end для текущего параграфа
    if current_paragraph:
        current_paragraph["page_end"] = page_num
    if current_chapter:
        current_chapter["page_end"] = page_num


# ---------------------------------------------------------------------------
# Извлечение ключевых элементов и сохранение результата
# ---------------------------------------------------------------------------
def extract_key_elements(
    paragraph: Dict[str, Any],
    page_words: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> None:
    """
    Извлекает ключевые элементы параграфа (даты, термины, персоналии)
    на основе форматирования шрифта.
    """
    formatting = config["formatting"]

    # Собираем весь текст параграфа для поиска дат
    full_text = paragraph["title"] + "\n" + paragraph["main_question"] + "\n"
    full_text += "\n".join(paragraph["content"]) + "\n"
    for section in paragraph["sections"]:
        full_text += section["title"] + "\n" + "\n".join(section["content"]) + "\n"
    for block_key, blocks in paragraph["special_blocks"].items():
        for block in blocks:
            full_text += block["header"] + "\n" + "\n".join(block["content"]) + "\n"

    # Даты (полужирный шрифт) — ищем по тексту
    if formatting["bold_dates"]:
        paragraph["key_elements"]["dates"] = extract_dates(full_text)

    # Термины (курсив) и персоналии (полужирный курсив) — по шрифтам
    if formatting["italic_terms"]:
        paragraph["key_elements"]["terms"] = extract_terms_from_words(page_words)
    if formatting["bold_italic_figures"]:
        paragraph["key_elements"]["figures"] = extract_figures_from_words(page_words)


def parse_textbook(pdf_path: str, config_path: str, output_path: str) -> Dict[str, Any]:
    """
    Основная функция: парсит PDF-учебник и сохраняет результат в JSON.

    Возвращает словарь с результатами парсинга.
    """
    config = load_config(config_path)
    chapters: List[Dict[str, Any]] = []

    logger.info("Начинаю обработку: %s", pdf_path)
    logger.info("Конфигурация: %s", config["book_line"])

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        logger.info("Всего страниц: %d", total_pages)

        for page_num, page in enumerate(pdf.pages, 1):
            parse_page(page, page_num, config, chapters)
            if page_num % 20 == 0 or page_num == total_pages:
                logger.info("Обработано страниц: %d / %d", page_num, total_pages)

    # Извлекаем ключевые элементы для каждого параграфа
    logger.info("Извлекаю ключевые элементы (даты, термины, персоналии)...")

    # Кэшируем слова всех страниц (открываем PDF один раз)
    page_words_cache: Dict[int, List[Dict[str, Any]]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for i in range(len(pdf.pages)):
            page_words_cache[i + 1] = pdf.pages[i].extract_words(
                extra_attrs=["fontname", "size"]
            )

    for chapter in chapters:
        for paragraph in chapter["paragraphs"]:
            # Собираем слова всех страниц параграфа из кэша
            page_words: List[Dict[str, Any]] = []
            start = paragraph["page_start"] or 1
            end = paragraph["page_end"] or start
            for i in range(start, min(end, len(page_words_cache)) + 1):
                page_words.extend(page_words_cache.get(i, []))
            extract_key_elements(paragraph, page_words, config)

    # Формируем итоговую структуру
    output_data = {
        "book_id": config["book_id"],
        "book_line": config["book_line"],
        "source_file": Path(pdf_path).name,
        "total_chapters": len(chapters),
        "total_paragraphs": sum(len(ch["paragraphs"]) for ch in chapters),
        "data": chapters,
    }

    # Сохраняем результат
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info("Готово! Глав: %d, параграфов: %d", output_data["total_chapters"], output_data["total_paragraphs"])
    logger.info("Результат сохранён: %s", output_path)

    return output_data


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def main() -> None:
    """Точка входа в скрипт."""
    if len(sys.argv) != 4:
        print("Использование: python parser.py <pdf_path> <config_path> <output_path>")
        print("Пример: python parser.py books/6_klass._Istoriya_Rossii.pdf config_russia_history.json output.json")
        sys.exit(1)

    pdf_path = sys.argv[1]
    config_path = sys.argv[2]
    output_path = sys.argv[3]

    if not Path(pdf_path).exists():
        logger.error("Файл PDF не найден: %s", pdf_path)
        sys.exit(1)
    if not Path(config_path).exists():
        logger.error("Файл конфигурации не найден: %s", config_path)
        sys.exit(1)

    parse_textbook(pdf_path, config_path, output_path)


if __name__ == "__main__":
    main()
