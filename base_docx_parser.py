# -*- coding: utf-8 -*-
"""
Единая основа парсера учебников истории (DOCX → структурированный JSON).

Базовый класс BaseDocxParser содержит общую логику обработки DOCX-учебника:
  - извлечение глав, параграфов (§), разделов, спецблоков;
  - извлечение ключевых элементов (даты, термины, персоналии);
  - фильтрацию «шума» (номера страниц, колонтитулы) и подписей к иллюстрациям.

Важно: текст НЕ сокращается и НЕ перефразируется — всё содержимое
сохраняется в исходном виде.

Для каждой конкретной книги создаётся свой подкласс, который переопределяет
специфичные методы (определение начала главы, номера, названия, заголовка
параграфа и т.д.), поскольку структура глав в разных учебниках различается.

Использование:
    from base_docx_parser import BaseDocxParser

    class Parser5Klass(BaseDocxParser):
        def is_chapter_number(self, paragraph):
            ...
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document
from docx.document import Document as DocumentObject
from docx.table import Table
from docx.text.paragraph import Paragraph

# ---------------------------------------------------------------------------
# Настройка логирования
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("history_docx_parser")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def load_config(config_path: str) -> Dict[str, Any]:
    """Загружает JSON-конфигурацию парсера."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_text(text: str) -> str:
    """Удаляет символы-артефакты из текста."""
    if not text:
        return text
    # Артефакт \uf401 — лишний символ из PDF-шрифтов, сохраняющийся в DOCX
    return text.replace("\uf401", "")


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


def detect_special_block(line: str, special_blocks: Dict[str, str]) -> Optional[str]:
    """
    Определяет, является ли строка заголовком специального блока.

    Возвращает ключ блока (например, "historical_portrait") или None.
    Маркеры проверяются от самых длинных к коротким, чтобы более
    специфичные заголовки (например, «ВОПРОСЫ И ЗАДАНИЯ К ГЛАВЕ»)
    распознавались раньше общих («ВОПРОСЫ И ЗАДАНИЯ»).
    """
    line_lower = line.lower()
    # Строки оглавления (например, «Вопросы и задания к главе\t143»)
    # содержат табуляцию и номер страницы — не считаем их спецблоками.
    if "\t" in line:
        return None
    for key, marker in sorted(
        special_blocks.items(), key=lambda kv: len(kv[1]), reverse=True
    ):
        if marker.lower() in line_lower:
            return key
    return None


def paragraph_text(paragraph: Paragraph) -> str:
    """Возвращает очищенный текст параграфа."""
    return clean_text(paragraph.text.strip())


def _is_year_range(text: str) -> bool:
    """Определяет, является ли текст диапазоном лет (например, «1914—1922 гг.»).

    Используется для продолжения названия главы в 10 классе История России,
    где после Heading 2 идёт Normal-параграф с годами.
    """
    t = text.strip()
    if not t:
        return False
    if len(t) > 40:
        return False
    return bool(re.search(r"\d{4}\s*[—–-]\s*\d{4}", t)) and "гг" in t


def paragraph_runs(paragraph: Paragraph) -> List[Dict[str, Any]]:
    """
    Возвращает список runs параграфа с текстом и форматированием.

    Каждый run — словарь: {"text", "bold", "italic"}.
    """
    runs: List[Dict[str, Any]] = []
    for r in paragraph.runs:
        text = clean_text(r.text)
        if text.strip():
            runs.append({
                "text": text,
                "bold": bool(r.bold),
                "italic": bool(r.italic),
            })
    return runs


def split_bold_part(runs: List[Dict[str, Any]]) -> str:
    """
    Возвращает полужирную часть параграфа (заголовок раздела).

    Собирает runs, набранные полужирным шрифтом, до первого
    обычного run.
    """
    if not runs:
        return ""

    bold_parts: List[str] = []
    for r in runs:
        if r["bold"]:
            bold_parts.append(r["text"])
        else:
            break

    return " ".join(bold_parts).strip()


def split_regular_part(runs: List[Dict[str, Any]]) -> str:
    """
    Возвращает обычную (не полужирную) часть параграфа.

    Собирает runs, набранные обычным шрифтом, после полужирной
    части (заголовка раздела).
    """
    if not runs:
        return ""

    regular_parts: List[str] = []
    found_regular = False
    for r in runs:
        if r["bold"]:
            if found_regular:
                regular_parts.append(r["text"])
        else:
            found_regular = True
            regular_parts.append(r["text"])

    if not found_regular:
        return ""

    return " ".join(regular_parts).strip()


# Слова из подписей к иллюстрациям, которые не являются терминами
CAPTION_WORDS = {
    "художник", "рисунок", "фото", "фотография", "икона", "гравюра",
    "миниатюра", "реконструкция", "музей", "общий", "вид", "рельеф",
    "здании", "фрагмент", "памятник", "картина", "портрет", "скульптура",
    "мозаика", "фреска", "барельеф", "статуя", "монета", "печать",
    "рукопись", "летопись", "свиток", "карта", "схема", "диаграмма",
    "государственный", "русский", "третьяковская", "галерея", "эрмитаж",
    "севастополь", "москва", "новгород", "киев", "петербург",
    "скульптор", "автор", "проекта", "середина", "собрания",
}


def is_caption_text(text: str) -> bool:
    """
    Проверяет, является ли текст подписью к иллюстрации.

    Подписи к иллюстрациям начинаются со слов из CAPTION_WORDS
    (например, «Художник Моллер», «Реконструкция М. Герасимова»).
    """
    text_lower = text.lower().strip()
    for word in CAPTION_WORDS:
        if text_lower.startswith(word):
            return True
    return False


def is_caption_paragraph(text: str, runs: Optional[List[Dict[str, Any]]] = None) -> bool:
    """
    Определяет, является ли параграф подписью к иллюстрации.

    Подписи к иллюстрациям в учебниках обычно начинаются с названия
    типа изображения («Памятник», «Художник», «Скульптор», «Икона»,
    «Музей», «Фрагмент» и т.п.) и содержат имена авторов и даты.
    Также подпись может начинаться с жирного названия события, а
    курсивная часть содержит тип изображения («Миниатюра», «Художник»,
    «Скульптор» и т.п.). Такие параграфы не являются частью учебного
    текста, поэтому их содержимое и runs не должны попадать в параграф.
    """
    text_lower = text.lower().strip()
    if not text_lower:
        return False

    # Слова-маркеры начала подписи к иллюстрации
    caption_markers = (
        "памятник", "художник", "скульптор", "икона", "музей",
        "фрагмент", "автор", "середина", "реконструкция", "миниатюра",
        "гравюра", "фреска", "мозаика", "статуя", "монета", "печать",
        "рукопись", "летопись", "свиток", "карта", "схема", "диаграмма",
        "общий вид", "деталь", "царский", "средневековая", "средневековый",
        "фото", "фотография", "картина", "портрет", "барельеф",
        "оружейная", "палата", "кремль", "рисунка", "рисунок",
        "государственная оружейная",
    )

    for marker in caption_markers:
        if text_lower.startswith(marker):
            return True

    # Если параграф начинается с жирного названия события, а курсивная
    # часть содержит тип изображения — это подпись к иллюстрации.
    if runs:
        italic_text = " ".join(r["text"] for r in runs if r["italic"]).lower()
        for marker in caption_markers:
            if marker in italic_text:
                return True

    return False


def extract_terms_from_runs(runs: List[Dict[str, Any]]) -> List[str]:
    """
    Извлекает термины (курсивные слова) из runs параграфа.

    Термины — слова, набранные курсивом (но не полужирным курсивом,
    который используется для персоналий). Подписи к иллюстрациям
    отфильтровываются.
    """
    terms: List[str] = []
    for r in runs:
        if r["italic"] and not r["bold"]:
            text = r["text"].strip(".,;:!?()«»\"")
            if len(text) > 2 and text not in terms:
                # Пропускаем подписи к иллюстрациям
                if is_caption_text(text):
                    continue
                # Пропускаем римские цифры (века) и числа — это не термины
                if re.match(r"^[IVXLCDM]+$", text.strip()) or re.match(r"^\d+", text.strip()):
                    continue
                terms.append(text)
    return terms


def extract_figures_from_runs(runs: List[Dict[str, Any]]) -> List[str]:
    """
    Извлекает персоналии (полужирный курсив) из runs параграфа.

    Персоналии — слова, набранные полужирным курсивом.
    """
    figures: List[str] = []
    for r in runs:
        if r["bold"] and r["italic"]:
            text = r["text"].strip(".,;:!?()«»\"")
            if len(text) > 2 and text not in figures:
                figures.append(text)
    return figures


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
        # Служебное поле: все runs, относящиеся к параграфу
        # (для извлечения терминов и персоналий по форматированию)
        "_runs": [],
    }


def new_section() -> Dict[str, Any]:
    """Создаёт пустую структуру раздела параграфа."""
    return {
        "number": "",
        "title": "",
        "content": [],
    }


def is_chapter_start(text: str, structure: Dict[str, Any]) -> bool:
    """
    Проверяет, является ли строка началом главы («Г Л А В А»).

    В DOCX «Г Л А В А» — отдельный параграф (Normal), за которым следуют
    номер главы (Heading 1) и название (Heading 2). Поэтому проверяем
    по упрощённому паттерну без захвата названия.
    """
    # Упрощённый паттерн: «Г Л А В А» с возможными пробелами между буквами
    if re.match(r"^\s*Г\s*Л\s*А\s*В\s*А\s*$", text):
        return True
    # Также поддерживаем вариант, когда название главы на той же строке
    return bool(re.match(structure["chapter"], text))


def is_paragraph_heading(paragraph: Paragraph) -> bool:
    """Проверяет, является ли параграф заголовком параграфа (§)."""
    text = paragraph.text.strip()
    # «иТоГи ГЛАВы» — это итоги главы, а не параграф
    if re.match(r"^иТоГи\s+ГЛАВы", text, re.IGNORECASE):
        return False
    if paragraph.style.name == "Heading 3":
        return True
    # В некоторых учебниках (например, 6 класс всеобщая история)
    # параграфы оформлены как Heading 2 с текстом, начинающимся с «§»
    if paragraph.style.name == "Heading 2" and text.startswith("§"):
        return True
    return False


def is_chapter_number(paragraph: Paragraph) -> bool:
    """Проверяет, является ли параграф номером главы (римская цифра)."""
    return paragraph.style.name == "Heading 1"


def is_chapter_title(paragraph: Paragraph) -> bool:
    """Проверяет, является ли параграф названием главы."""
    # Heading 2 с «§» — это параграф, а не название главы
    if paragraph.style.name == "Heading 2" and paragraph.text.strip().startswith("§"):
        return False
    return paragraph.style.name == "Heading 2"


def is_chapter_summary(paragraph: Paragraph) -> bool:
    """Проверяет, является ли параграф итогами главы."""
    if paragraph.style.name == "Heading 4":
        return True
    # В некоторых учебниках (например, 6 класс всеобщая история)
    # итоги главы оформлены как Heading 3 с текстом «иТоГи ГЛАВы»
    if re.match(r"^иТоГи\s+ГЛАВы", paragraph.text.strip(), re.IGNORECASE):
        return True
    return False


def is_appendix(paragraph: Paragraph) -> bool:
    """Проверяет, является ли параграф приложением (введение, словарь и т.д.)."""
    return paragraph.style.name == "Heading 5"





# ---------------------------------------------------------------------------
# Базовый класс парсера
# ---------------------------------------------------------------------------
class BaseDocxParser:
    """
    Единая основа парсера DOCX-учебников истории.

    Содержит общую логику обработки документа. Для каждой конкретной
    книги создаётся подкласс, переопределяющий специфичные методы:
      - is_chapter_start / is_chapter_number / is_chapter_title
      - collect_chapter_title (сбор названия главы)
      - is_paragraph_heading
      - is_noise_line / is_footer_line
      - is_caption_paragraph
    """

    # Имя книги (для реестра парсеров)
    book_name = "base"

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.structure = config["structure"]
        self.special_blocks = config["special_blocks"]
        self.noise_patterns = config["noise_patterns"]
        self.footer_patterns = config["footer_patterns"]

    # ------------------------------------------------------------------
    # Методы, специфичные для конкретной книги (переопределяются)
    # ------------------------------------------------------------------
    def is_chapter_start(self, text: str) -> bool:
        """
        Проверяет, является ли строка началом главы («Г Л А В А»).

        В DOCX «Г Л А В А» — отдельный параграф (Normal), за которым следуют
        номер главы (Heading 1) и название (Heading 2). Поэтому проверяем
        по упрощённому паттерну без захвата названия.
        """
        if re.match(r"^\s*Г\s*Л\s*А\s*В\s*А\s*$", text):
            return True
        return bool(re.match(self.structure["chapter"], text))

    def is_chapter_number(self, paragraph: Paragraph) -> bool:
        """Проверяет, является ли параграф номером главы (римская цифра)."""
        return paragraph.style.name == "Heading 1"

    def is_chapter_title(self, paragraph: Paragraph) -> bool:
        """Проверяет, является ли параграф названием главы."""
        # Heading 2 с «§» — это параграф, а не название главы
        if paragraph.style.name == "Heading 2" and paragraph.text.strip().startswith("§"):
            return False
        return paragraph.style.name == "Heading 2"

    def is_paragraph_heading(self, paragraph: Paragraph) -> bool:
        """Проверяет, является ли параграф заголовком параграфа (§)."""
        text = paragraph.text.strip()
        # «иТоГи ГЛАВы» — это итоги главы, а не параграф
        if re.match(r"^иТоГи\s+ГЛАВы", text, re.IGNORECASE):
            return False
        if paragraph.style.name == "Heading 3":
            return True
        # В некоторых учебниках (например, 6 класс всеобщая история)
        # параграфы оформлены как Heading 2 с текстом, начинающимся с «§»
        if paragraph.style.name == "Heading 2" and text.startswith("§"):
            return True
        return False

    def is_chapter_summary(self, paragraph: Paragraph) -> bool:
        """Проверяет, является ли параграф итогами главы."""
        if paragraph.style.name == "Heading 4":
            return True
        # В некоторых учебниках (например, 6 класс всеобщая история)
        # итоги главы оформлены как Heading 3 с текстом «иТоГи ГЛАВы»
        if re.match(r"^иТоГи\s+ГЛАВы", paragraph.text.strip(), re.IGNORECASE):
            return True
        return False

    def is_appendix(self, paragraph: Paragraph) -> bool:
        """Проверяет, является ли параграф приложением (введение, словарь и т.д.)."""
        return paragraph.style.name == "Heading 5"

    def is_noise_line(self, text: str) -> bool:
        """Проверяет, является ли строка «шумом» (номера страниц, колонтитулы)."""
        return is_noise_line(text, self.noise_patterns)

    def is_footer_line(self, text: str) -> bool:
        """Проверяет, является ли строка колонтитулом (служебной информацией)."""
        return is_footer_line(text, self.footer_patterns)

    def is_caption_paragraph(self, text: str, runs: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Определяет, является ли параграф подписью к иллюстрации."""
        return is_caption_paragraph(text, runs)

    def new_paragraph(self) -> Dict[str, Any]:
        """Создаёт пустую структуру параграфа."""
        return new_paragraph()

    def new_section(self) -> Dict[str, Any]:
        """Создаёт пустую структуру раздела параграфа."""
        return new_section()

    def collect_chapter_title(self, paragraph, text, current_chapter,
                           collecting_chapter_name, collecting_chapter_title,
                           pending_paragraph_number) -> str:
        """
        Собирает название главы (после номера главы, до первого параграфа §).

        Возвращает строку-статус:
          - "add"      — текст добавлен к названию, сбор продолжается;
          - "add_stop" — текст добавлен к названию, сбор завершён;
          - "skip"     — элемент пропущен (подпись, вопрос, шум), сбор завершён;
          - "paragraph"— название главы закончилось, элемент — начало параграфа.
        """
        # Если это заголовок параграфа (§) или Heading 2 с ожидаемым
        # номером параграфа (pending_paragraph_number) — название главы
        # закончилось, обрабатываем параграф в шаге 2.
        if self.is_paragraph_heading(paragraph) or (
            pending_paragraph_number and paragraph.style.name == "Heading 2"
        ):
            return "paragraph"
        # Подписи к иллюстрациям, главный вопрос, эпиграфы и «шум»
        # не входят в название главы — пропускаем их и завершаем сбор.
        if self.is_caption_paragraph(text, paragraph_runs(paragraph)):
            return "skip"
        if "?" in text:
            return "skip"
        # Эпиграфы в начале главы (текст в «...» с указанием автора)
        # не входят в название главы.
        if text.startswith("«"):
            return "skip"
        # Подписи к иллюстрациям в этих учебниках — смешанное
        # форматирование: жирная часть + курсивная часть
        # (например, «Мечеть Аль-Харам в Мекке. Современный вид»).
        # Название главы обычно не выделено так.
        runs = paragraph_runs(paragraph)
        if runs and any(r.get("bold") for r in runs) and any(r.get("italic") for r in runs):
            return "skip"
        # Название главы может быть в нескольких параграфах
        # (Normal и Heading 2). Добавляем их к заголовку главы.
        if current_chapter["title"]:
            current_chapter["title"] += " " + text
        else:
            current_chapter["title"] = text
        # Heading 2 завершает название главы
        if self.is_chapter_title(paragraph):
            return "add_stop"
        return "add"

    def assign_chapter_numbers(self, chapters: List[Dict[str, Any]]) -> None:
        """
        Доназначает номера глав, если в книге они не проставлены.

        В некоторых учебниках номер главы (римская цифра) присутствует
        только у части глав. Здесь мы восстанавливаем номера по порядку
        следования глав (I, II, III, ...). Подклассы могут переопределить
        этот метод для книг с другой нумерацией.
        """
        roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
                "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII",
                "XIX", "XX", "XXI", "XXII", "XXIII", "XXIV", "XXV"]
        for idx, chapter in enumerate(chapters):
            if not chapter.get("number"):
                if idx < len(roman):
                    chapter["number"] = roman[idx]

    # ------------------------------------------------------------------
    # Основной цикл обработки документа
    # ------------------------------------------------------------------

    def parse_document(self, doc: DocumentObject) -> List[Dict[str, Any]]:
        """
        Обрабатывает DOCX-документ: извлекает главы, параграфы, разделы,
        спецблоки и ключевые элементы.
        """
        chapters: List[Dict[str, Any]] = []

        # Текущий контекст
        current_chapter: Optional[Dict[str, Any]] = None
        current_paragraph: Optional[Dict[str, Any]] = None
        current_section: Optional[Dict[str, Any]] = None
        current_block: Optional[str] = None  # ключ текущего спецблока

        # Флаг: идёт ли сбор заголовка главы (многострочный заголовок)
        collecting_chapter_title = False
        # Флаг: идёт ли сбор заголовка параграфа (разбит на 2 части)
        collecting_paragraph_title = False
        # Флаг: идёт ли сбор названия главы (после номера главы)
        collecting_chapter_name = False
        # Номер параграфа, найденный в отдельном Normal-параграфе «§ N»
        # (в некоторых учебниках номер параграфа идёт отдельно от названия)
        pending_paragraph_number = ""

        # Собираем все элементы документа в порядке следования
        # (параграфы и таблицы)
        elements: List[Any] = []
        for child in doc.element.body:
            if child.tag.endswith("}p"):
                elements.append(Paragraph(child, doc))
            elif child.tag.endswith("}tbl"):
                elements.append(Table(child, doc))

        for idx, element in enumerate(elements):
            # Обрабатываем таблицы (синхронистические таблицы)
            if isinstance(element, Table):
                if current_paragraph is not None:
                    for row in element.rows:
                        for cell in row.cells:
                            cell_text = clean_text(cell.text.strip())
                            if cell_text:
                                current_paragraph["sync_table"].append(cell_text)
                continue

            paragraph = element
            text = paragraph_text(paragraph)
            if not text:
                continue

            # Пропускаем «шум» и колонтитулы
            if self.is_noise_line(text) or self.is_footer_line(text):
                continue

            style = paragraph.style.name
            runs = paragraph_runs(paragraph)

            # 0. Обработка отдельного номера параграфа «§ N» (Normal).
            # В некоторых учебниках (например, 6 класс всеобщая история)
            # номер параграфа идёт отдельным Normal-параграфом, а название —
            # следующим Heading 2. Запоминаем номер и ждём название.
            if style == "Normal" and re.match(r"^\s*§\s*\d+(?:[–-]\d+)?\s*$", text):
                pending_paragraph_number = text.strip().lstrip("§").strip()
                continue

            # 1. Проверка на начало главы («Г Л А В А»)
            if self.is_chapter_start(text):
                chapter = {
                    "title": "",
                    "number": "",
                    "page_start": None,
                    "page_end": None,
                    "paragraphs": [],
                }
                chapters.append(chapter)
                current_chapter = chapter
                current_paragraph = None
                current_section = None
                current_block = None
                collecting_chapter_title = True
                collecting_chapter_name = False
                collecting_paragraph_title = False
                pending_paragraph_number = ""
                continue

            # 1.1. Номер главы (римская цифра)
            if collecting_chapter_title and current_chapter and self.is_chapter_number(paragraph):
                current_chapter["number"] = text
                collecting_chapter_title = False
                collecting_chapter_name = True
                continue

            # 1.2. Сбор названия главы (после номера главы, до первого параграфа §)
            if (collecting_chapter_name or collecting_chapter_title) and current_chapter:
                status = self.collect_chapter_title(
                    paragraph, text, current_chapter,
                    collecting_chapter_name, collecting_chapter_title,
                    pending_paragraph_number,
                )
                if status == "add":
                    # Название главы ещё собирается
                    continue
                elif status == "add_stop":
                    # Название главы добавлено и сбор завершён.
                    # В некоторых книгах (10 класс История России) название
                    # главы может продолжаться Normal-параграфом с датами
                    # (например, «1914—1922 гг.») сразу после Heading 2.
                    # Если следующий параграф — Normal с датами, продолжаем сбор.
                    nxt = elements[idx + 1] if idx + 1 < len(elements) else None
                    if (
                        nxt is not None
                        and not isinstance(nxt, Table)
                        and nxt.style.name == "Normal"
                        and _is_year_range(paragraph_text(nxt))
                    ):
                        collecting_chapter_name = True
                        collecting_chapter_title = False
                        continue
                    collecting_chapter_name = False
                    collecting_chapter_title = False
                    continue
                elif status == "skip":
                    # Элемент пропущен (подпись, вопрос, шум), сбор завершён
                    collecting_chapter_name = False
                    collecting_chapter_title = False
                    continue
                else:  # status == "paragraph"
                    # Название главы закончилось — обрабатываем как параграф ниже
                    collecting_chapter_name = False
                    collecting_chapter_title = False

            # 2. Проверка на заголовок параграфа (§)
            # Если номер параграфа был найден в отдельном Normal-параграфе
            # «§ N», то следующий Heading 2 — это название параграфа.
            is_para_heading = self.is_paragraph_heading(paragraph) or (
                pending_paragraph_number and style == "Heading 2"
            )
            if is_para_heading:
                # Сбрасываем сбор названия главы
                collecting_chapter_name = False
                collecting_chapter_title = False

                # Извлекаем номер параграфа, если он есть.
                # Заголовок может быть «§ 12» (только номер) или
                # «§ 1 Название» (номер + название).
                para_match = re.match(self.structure["paragraph"], text)
                para_number = para_match.group(1) if para_match else ""
                if not para_number:
                    # Пробуем извлечь номер из «§ 12» (без названия)
                    num_match = re.match(r"^\s*§\s*(\d+(?:[–-]\d+)?)\s*$", text)
                    if num_match:
                        para_number = num_match.group(1)
                # Если номер параграфа был найден в отдельном Normal-параграфе
                # «§ N» (pending_paragraph_number), используем его.
                if not para_number and pending_paragraph_number:
                    para_number = pending_paragraph_number
                pending_paragraph_number = ""

                if current_chapter:
                    # Если предыдущий параграф был разбит на 2 части,
                    # объединяем заголовки
                    if collecting_paragraph_title and current_paragraph:
                        current_paragraph["title"] += " " + text
                        # Оставляем collecting_paragraph_title = True,
                        # чтобы главный вопрос распознавался после названия
                        continue

                    para = self.new_paragraph()
                    para["title"] = text
                    para["number"] = para_number
                    para["_runs"].extend(runs)
                    current_chapter["paragraphs"].append(para)
                    current_paragraph = para
                    current_section = None
                    current_block = None
                    collecting_paragraph_title = True
                    continue

            # 3. Проверка на итоги главы (Heading 4)
            if self.is_chapter_summary(paragraph) and current_paragraph:
                block_key = detect_special_block(text, self.special_blocks)
                if block_key:
                    if block_key not in current_paragraph["special_blocks"]:
                        current_paragraph["special_blocks"][block_key] = []
                    current_paragraph["special_blocks"][block_key].append({
                        "header": text,
                        "content": [],
                    })
                    current_block = block_key
                    current_section = None
                    continue

            # 4. Проверка на приложение (Heading 5) — пропускаем
            if self.is_appendix(paragraph):
                continue

            # 5. Проверка на специальный блок
            block_key = detect_special_block(text, self.special_blocks)
            if block_key and current_paragraph:
                if block_key not in current_paragraph["special_blocks"]:
                    current_paragraph["special_blocks"][block_key] = []
                current_paragraph["special_blocks"][block_key].append({
                    "header": text,
                    "content": [],
                })
                current_block = block_key
                current_section = None
                collecting_paragraph_title = False
                continue

            # 6. Проверка на главный вопрос параграфа
            if current_paragraph and current_paragraph["main_question"] == "":
                # «?» — разделитель между номером и названием параграфа,
                # пропускаем его, не сбрасывая сбор заголовка параграфа.
                if re.match(r"^\s*\?\s*$", text):
                    continue

                # Главный вопрос может начинаться с «?» или быть первым
                # жирным параграфом после заголовка параграфа (не разделом).
                mq_match = re.match(self.structure["main_question"], text)
                is_bold_paragraph = runs and runs[0]["bold"]
                is_section_start = bool(re.match(self.structure["section"], text))
                if mq_match:
                    current_paragraph["main_question"] = mq_match.group(1)
                    collecting_paragraph_title = False
                    continue
                elif is_bold_paragraph and not is_section_start and collecting_paragraph_title:
                    current_paragraph["main_question"] = text
                    collecting_paragraph_title = False
                    continue

            # 7. Проверка на раздел (нумерованный заголовок)
            if current_paragraph and current_block is None:
                sec_match = re.match(self.structure["section"], text)
                if sec_match and runs and runs[0]["bold"]:
                    section = self.new_section()
                    section["number"] = sec_match.group(1)

                    # Заголовок раздела — только полужирная часть параграфа
                    bold_part = split_bold_part(runs)
                    if bold_part:
                        # Убираем номер из заголовка
                        section["title"] = re.sub(r"^\s*\d+\s+", "", bold_part)
                    else:
                        section["title"] = sec_match.group(2)

                    current_paragraph["sections"].append(section)
                    current_section = section
                    collecting_paragraph_title = False

                    # Если после заголовка на той же строке есть обычный текст
                    # (не полужирный), добавляем его в содержимое раздела
                    regular_part = split_regular_part(runs)
                    if regular_part:
                        current_section["content"].append(regular_part)
                    continue

            # 8. Проверка на синхронистическую таблицу
            if current_paragraph and re.search(self.structure["sync_table"], text):
                current_paragraph["sync_table"].append(text)
                continue

            # 9. Обычный текст — добавляем в текущий контекст.
            # Подписи к иллюстрациям пропускаем (не являются учебным текстом).
            if self.is_caption_paragraph(text, runs):
                continue

            # Если заголовок параграфа был разбит на 2 части и следующая часть —
            # Heading 2, Heading 3 или Normal (продолжение названия параграфа),
            # объединяем их. Heading 3 без «§» — это название параграфа
            # (например, в 10 классе История России номер «§ 10» и название
            # идут отдельными Heading 3). Normal — название параграфа в тех
            # случаях, когда оно оформлено обычным текстом (например, «§ 25—26»).
            # Служебные заголовки (колонтитулы, итоги главы) не объединяем.
            if (
                collecting_paragraph_title
                and current_paragraph
                and style in ("Heading 2", "Heading 3", "Normal")
                and "?" not in text
                and not self.is_noise_line(text)
                and not self.is_chapter_summary(paragraph)
            ):
                current_paragraph["title"] += " " + text
                continue

            if current_block and current_paragraph:
                # Текст внутри спецблока
                current_paragraph["special_blocks"][current_block][-1]["content"].append(text)
            elif current_section:
                current_section["content"].append(text)
            elif current_paragraph:
                current_paragraph["content"].append(text)

            # Собираем runs для извлечения терминов и персоналий
            # (только для параграфов, не для глав/приложений)
            if current_paragraph and not collecting_chapter_title and not collecting_chapter_name:
                current_paragraph["_runs"].extend(runs)

        return chapters




    # ------------------------------------------------------------------
    # Извлечение ключевых элементов
    # ------------------------------------------------------------------

    def extract_key_elements(self, paragraph: Dict[str, Any]) -> None:
        """
        Извлекает ключевые элементы параграфа (даты, термины, персоналии)
        на основе форматирования runs.
        """
        formatting = self.config["formatting"]

        # Собираем весь текст параграфа для поиска дат
        full_text = paragraph["title"] + "\n" + paragraph["main_question"] + "\n"
        full_text += "\n".join(paragraph["content"]) + "\n"
        for section in paragraph["sections"]:
            full_text += section["title"] + "\n" + "\n".join(section["content"]) + "\n"
        for block_key, blocks in paragraph["special_blocks"].items():
            for block in blocks:
                full_text += block["header"] + "\n" + "\n".join(block["content"]) + "\n"

        # Даты — ищем по тексту
        if formatting["bold_dates"]:
            paragraph["key_elements"]["dates"] = extract_dates(full_text)

        # Термины (курсив) и персоналии (полужирный курсив) — по runs
        runs = paragraph.get("_runs", [])
        if formatting["italic_terms"]:
            paragraph["key_elements"]["terms"] = extract_terms_from_runs(runs)
        if formatting["bold_italic_figures"]:
            paragraph["key_elements"]["figures"] = extract_figures_from_runs(runs)

        # Удаляем служебное поле _runs из итогового результата
        paragraph.pop("_runs", None)




    def parse_textbook(self, docx_path: str, output_path: str) -> Dict[str, Any]:
        """
        Основная функция: парсит DOCX-учебник и сохраняет результат в JSON.

        Возвращает словарь с результатами парсинга.
        """
        logger.info("Начинаю обработку: %s", docx_path)
        logger.info("Конфигурация: %s", self.config["book_line"])

        doc = Document(docx_path)
        logger.info("Всего параграфов: %d", len(doc.paragraphs))

        chapters = self.parse_document(doc)

        # Доназначаем номера глав (если в книге они не проставлены)
        self.assign_chapter_numbers(chapters)

        # Извлекаем ключевые элементы для каждого параграфа
        logger.info("Извлекаю ключевые элементы (даты, термины, персоналии)...")

        for chapter in chapters:
            for paragraph in chapter["paragraphs"]:
                self.extract_key_elements(paragraph)

        # Формируем итоговую структуру
        output_data = {
            "book_id": self.config["book_id"],
            "book_line": self.config["book_line"],
            "source_file": Path(docx_path).name,
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
