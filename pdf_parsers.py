# -*- coding: utf-8 -*-
"""
PDF-парсеры для учебников 11 класса.

DOCX-версии учебников 11 класса имеют некорректную структуру (мусор в
названиях глав, разделы вместо параграфов §). Поэтому для них используются
PDF-версии, где структура глав и параграфов «§ N» корректная.

Каждый PDF-парсер возвращает ту же структуру, что и DOCX-парсеры:
  главы → параграфы (title, number, page_start, page_end, content, ...).

Для каждой книги — свой класс (не ломая существующие DOCX-парсеры).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

import pdfplumber

logger = logging.getLogger("pdf_parsers")


def _clean_titles_with_llm(titles: List[str]) -> List[str]:
    """Очищает названия параграфов/глав от мусора через LLM (DeepSeek).

    Убирает точки-заполнители, номера страниц, колонтитулы, копирайты,
    лишние дефисы и прочий мусор из оглавления PDF. При недоступности LLM
    или некорректном ответе возвращает исходные названия (fallback).
    """
    if not titles:
        return titles
    try:
        from services.llm_service import call_llm

        prompt = (
            "Ниже список названий параграфов и глав учебника истории. "
            "Очисти каждое название от мусора: точек-заполнителей (....), номеров страниц, "
            "колонтитулов, копирайтов (©), слов 'Оглавление', 'Итоги главы', лишних дефисов в начале. "
            "НЕ меняй смысл и формулировку названия, только убери мусор. "
            "Верни ТОЛЬКО JSON-массив строк в том же порядке, без пояснений.\n\n"
            + json.dumps(titles, ensure_ascii=False)
        )
        result = call_llm(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=2000,
            json_mode=True,
        )
        if isinstance(result, list) and len(result) == len(titles):
            cleaned = [str(t).strip() for t in result]
            # Защита от зацикливания: если LLM вернул пустые/некорректные значения,
            # оставляем исходные названия для этих позиций.
            return [c if c else orig for c, orig in zip(cleaned, titles)]
        logger.warning("LLM вернул некорректный результат очистки названий, использую исходные")
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM-очистка названий недоступна (%s), использую исходные", e)
    return titles


def _group_lines(words: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Группирует слова в строки по вертикальной позиции."""
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines, cur, cur_top = [], [], None
    for w in words:
        if cur_top is None or abs(w["top"] - cur_top) <= 2.0:
            cur.append(w)
            cur_top = w["top"] if cur_top is None else cur_top
        else:
            lines.append(cur)
            cur = [w]
            cur_top = w["top"]
    if cur:
        lines.append(cur)
    return lines


def _line_text(line: List[Dict[str, Any]]) -> str:
    return " ".join(w["text"] for w in sorted(line, key=lambda w: w["x0"])).strip()


def _line_size(line: List[Dict[str, Any]]) -> float:
    return max(w["size"] for w in line)


def _normalize_title_case(text: str) -> str:
    """Приводит заголовок к нормальному регистру.

    В PDF-учебниках 11 класса заголовки набраны «капсом с прописными
    буквами в середине слов» (например «СтрАны ЕВрОпы ВО»). Приводим
    к обычному виду: «Страны Европы во...».
    """
    if not text:
        return text
    # Слова, которые всегда пишутся с маленькой буквы (предлоги/союзы)
    lower_words = {
        "в", "во", "и", "с", "со", "на", "по", "за", "из", "до", "от",
        "о", "об", "к", "ко", "при", "для", "над", "под", "без", "у",
        "а", "но", "или", "не", "ни", "же", "бы", "ли", "хх", "xxi",
    }
    # Слова, которые всегда пишутся с большой буквы
    upper_words = {"сша", "ссср", "нато", "оон", "еэс", "евросоюз"}
    # Римские цифры (кириллица и латиница) — всегда в верхнем регистре
    roman_numerals = {
        "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
        "xi", "xii", "xiii", "xiv", "xv", "xx", "xxi", "xxii", "xxiii",
        "х", "хi", "хii", "хiii", "хiv", "хv", "хх", "ххi", "ххii", "ххiii",
    }

    words = text.split()
    result = []
    for i, w in enumerate(words):
        wl = w.lower()
        if wl in upper_words:
            w = w.upper()
        elif wl in roman_numerals:
            w = w.upper()
        elif wl in lower_words:
            w = w.lower()
        elif w.isupper() and len(w) > 1:
            # Капс: «ЕВРОПЫ» -> «Европы»
            w = w.capitalize()
        elif not w.islower() and not w.isupper():
            # Смешанный регистр с внутренними заглавными: «СтрАны» -> «Страны»
            w = w.capitalize()
        # Иначе слово уже в нормальном регистре («Развитие», «развитие») — не трогаем
        result.append(w)
    return " ".join(result)


# Однобуквенные предлоги/союзы — их НЕ склеиваем со следующим словом
_SINGLE_LETTER_WORDS = {"в", "с", "к", "о", "у", "и", "а", "я"}
# Двухбуквенные предлоги — перенос слова никогда не продолжается предлогом,
# поэтому строку, заканчивающуюся на «-», с такой строкой НЕ склеиваем.
_TWO_LETTER_PREPOSITIONS = {
    "на", "по", "за", "из", "до", "от", "об", "во", "со", "ко",
    "при", "над", "под", "без", "для",
}


def _join_hyphenated(lines: List[str]) -> List[str]:
    """Склеивает перенесённые слова в конце строк.

    В PDF текст разбит по строкам, и слова переносятся по дефису:
      «...третьей миро-» + «вой войны...» -> «...третьей мировой войны...»
    Также убирает случайные пробелы внутри слов («г раницах» -> «границах»),
    но НЕ склеивает однобуквенные предлоги («с наведёнными» остаётся)
    и НЕ склеивает перенос, если следующая строка начинается с предлога
    («...трактор-» + «на славу...» остаётся раздельно, а не «тракторна»).

    Дополнительно обрабатывает символ «⬤» (U+2B24) — артефакт PDF-шрифтов,
    используемый как маркер переноса слова:
      - «пред⬤» + «принимало» -> «предпринимало» (склейка строк)
      - «Объ⬤ясните» -> «Объясните» (удаление внутри слова)
      - строка, состоящая только из «⬤», удаляется.
    """
    if not lines:
        return lines
    joined: List[str] = []
    for line in lines:
        if not line:
            continue
        # Строка, состоящая только из «⬤» (маркер переноса на отдельной строке) — удаляем.
        if line.strip() == "⬤":
            continue
        # Если предыдущая строка заканчивается на «⬤» (маркер переноса слова),
        # склеиваем её с текущей строкой.
        if joined and joined[-1].endswith("⬤"):
            first_word = line.split()[0].lower() if line.split() else ""
            if first_word not in _TWO_LETTER_PREPOSITIONS:
                joined[-1] = joined[-1].rstrip("⬤") + line
                continue
        # Удаляем «⬤» внутри строки (артефакт, разрывающий слово).
        # Если строка заканчивалась на «⬤», сохраняем его в конце как маркер
        # переноса для следующей строки.
        ends_with_circle = line.endswith("⬤")
        line = line.replace("⬤", "")
        if ends_with_circle:
            line += "⬤"
        # Случайный пробел внутри слова: «г раницах» -> «границах».
        # Склеиваем только если первая буква — не однобуквенный предлог/союз.
        line = re.sub(
            r"\b([а-яёa-z]) ([а-яёa-z]{2,})\b",
            lambda m: m.group(1) + m.group(2) if m.group(1).lower() not in _SINGLE_LETTER_WORDS else m.group(0),
            line,
        )
        if joined and joined[-1].endswith("-"):
            # Перенос слова не продолжается предлогом — не склеиваем
            first_word = line.split()[0].lower() if line.split() else ""
            if first_word in _TWO_LETTER_PREPOSITIONS:
                joined.append(line)
            else:
                # Склеиваем перенесённое слово
                joined[-1] = joined[-1][:-1] + line
        else:
            joined.append(line)
    # Финальная очистка: убираем оставшиеся «⬤» (если перенос был в конце
    # последней строки и не с чем склеить).
    return [l.replace("⬤", "") for l in joined]


def _new_paragraph() -> Dict[str, Any]:
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


class Parser11KlassVseobschayaPdf:
    """11 класс — Всеобщая история (PDF).

    Структура:
      - Главы: «ГЛАВА НАЗВАНИЕ» (шрифт ReformaGroteskDemi, размер 40).
      - Параграфы: «§ N» — в PDF нет явных заголовков в теле, но есть
        колонтитул «§ N» на каждой чётной странице. По колонтитулам
        определяем, какой параграф занимает какие страницы, и собираем
        текст параграфа из его страниц.
    """

    is_pdf_parser = True

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.start_page = 8  # первая глава в теле (страницы 1-7 — титул/оглавление)

    def _extract_toc(self, pdf_path: str) -> Dict[str, Any]:
        """Извлекает оглавление (стр. 4): списки глав и параграфов с номерами и названиями.

        Возвращает:
            {"chapters": [{number, title, page}], "paragraphs": [{number, title, page}]}
        """
        chapters: List[Dict[str, Any]] = []
        paragraphs: List[Dict[str, Any]] = []
        with pdfplumber.open(pdf_path) as pdf:
            words = pdf.pages[3].extract_words(extra_attrs=["fontname", "size"])
        lines = [_line_text(l) for l in _group_lines(words)]
        lines = [l for l in lines if l]

        cur: Dict[str, Any] | None = None
        for text in lines:
            # Параграф «§ N» (проверяем первым — в оглавлении их больше)
            m = re.match(r"^§\s*(\d+(?:[—–-]\d+)?)\.?\s*(.*)$", text)
            if m:
                if cur:
                    (chapters if cur["type"] == "chapter" else paragraphs).append(cur)
                cur = {"type": "paragraph", "number": m.group(1), "title": m.group(2).strip()}
                pm = re.search(r"\.{3,}\s*(\d+)\s*$", text)
                if pm:
                    cur["page"] = int(pm.group(1))
                continue
            # Глава «Глава I.»
            m = re.match(r"^Глава\s+([IVXLC]+)\.\s*(.*)$", text)
            if m:
                if cur:
                    (chapters if cur["type"] == "chapter" else paragraphs).append(cur)
                cur = {"type": "chapter", "number": m.group(1), "title": m.group(2).strip()}
                pm = re.search(r"\.{3,}\s*(\d+)\s*$", text)
                if pm:
                    cur["page"] = int(pm.group(1))
                continue
            # Продолжение многострочной записи
            if cur and text and not re.match(
                r"^(Вопросы|Темы|Ресурсы|Дополнительные|Заключение|Словарь|Основные|Интернет|Введение)",
                text,
            ):
                clean = re.sub(r"\s*\.{3,}\s*\d*\s*$", "", text).strip()
                if clean:
                    cur["title"] += " " + clean
                pm = re.search(r"\.{3,}\s*(\d+)\s*$", text)
                if pm:
                    cur["page"] = int(pm.group(1))
        if cur:
            (chapters if cur["type"] == "chapter" else paragraphs).append(cur)

        # Очищаем названия от точек-заполнителей и номеров страниц
        for item in chapters + paragraphs:
            title = re.sub(r"\s*\.{3,}\s*\d*\s*$", "", item["title"]).strip()
            # Номер страницы в конце без точек-заполнителей («...в. 115» -> «...в.»)
            title = re.sub(r"\s+\d{1,3}\s*$", "", title).strip()
            item["title"] = title
        # Дополнительная очистка названий через LLM (убирает остаточный мусор)
        all_titles = [item["title"] for item in chapters + paragraphs]
        cleaned = _clean_titles_with_llm(all_titles)
        for item, title in zip(chapters + paragraphs, cleaned):
            item["title"] = title
        return {"chapters": chapters, "paragraphs": paragraphs}

    def parse_document(self, pdf_path: str) -> List[Dict[str, Any]]:
        chapters: List[Dict[str, Any]] = []
        page_para: Dict[int, str] = {}  # page_num -> номер параграфа
        page_header: Dict[int, bool] = {}  # page_num -> это заголовок параграфа?

        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            # Кэш слов по страницам — извлекаем один раз (оптимизация)
            page_words: Dict[int, List[Dict[str, Any]]] = {}

            def get_words(pn: int) -> List[Dict[str, Any]]:
                if pn not in page_words:
                    page_words[pn] = pdf.pages[pn].extract_words(extra_attrs=["fontname", "size"])
                return page_words[pn]

            # Шаг 1: определяем параграф на каждой странице (по колонтитулу/заголовку)
            for pn in range(self.start_page - 1, total):
                words = get_words(pn)
                if not words:
                    continue
                for line in _group_lines(words):
                    text = _line_text(line)
                    if not text:
                        continue
                    size = _line_size(line)
                    m = re.match(r"^\s*§\s*(\d+(?:[–-]\d+)?)", text)
                    if m:
                        page_para[pn + 1] = m.group(1)
                        page_header[pn + 1] = size >= 18
                        break

            # Шаг 2: заполняем страницы без колонтитула (нечётные) — наследуем
            for pn in range(self.start_page, total + 1):
                if pn not in page_para:
                    prev = pn - 1
                    while prev >= self.start_page and prev not in page_para:
                        prev -= 1
                    if prev in page_para:
                        page_para[pn] = page_para[prev]
                        page_header[pn] = False

            # Шаг 3: определяем главы (по «ГЛАВА» size>=30)
            chapter_pages: List[int] = []
            for pn in range(self.start_page - 1, total):
                words = get_words(pn)
                if not words:
                    continue
                for line in _group_lines(words):
                    text = _line_text(line)
                    if not text:
                        continue
                    size = _line_size(line)
                    if re.match(r"^\s*ГЛАВА\s+", text) and size >= 30:
                        chapter_pages.append(pn + 1)
                        break

            # Шаг 4: собираем главы и параграфы
            # Группируем параграфы по главам (по страницам начала глав)
            para_list = sorted(page_para.items(), key=lambda x: x[0])
            # Строим список параграфов с диапазонами страниц
            para_ranges: List[Dict[str, Any]] = []
            for i, (pn, num) in enumerate(para_list):
                if page_header.get(pn, False):
                    # Заголовок параграфа — начало нового параграфа
                    para_ranges.append({"number": num, "page_start": pn, "page_end": pn})
                elif para_ranges and para_ranges[-1]["number"] == num:
                    para_ranges[-1]["page_end"] = pn
                elif para_ranges:
                    # Смена параграфа без явного заголовка — новый параграф
                    para_ranges.append({"number": num, "page_start": pn, "page_end": pn})

            # Привязываем параграфы к главам
            for ch_idx, ch_page in enumerate(chapter_pages):
                ch_end = chapter_pages[ch_idx + 1] if ch_idx + 1 < len(chapter_pages) else total + 1
                chapter = {"title": "", "number": "", "page_start": ch_page,
                           "page_end": ch_end - 1, "paragraphs": []}
                chapters.append(chapter)

            # Распределяем параграфы по главам
            for pr in para_ranges:
                for ch in chapters:
                    if ch["page_start"] <= pr["page_start"] <= ch["page_end"]:
                        ch["paragraphs"].append(pr)
                        break

            # Шаг 5: собираем текст параграфов и названия глав
            collecting_question = False
            for pn in range(self.start_page - 1, total):
                words = get_words(pn)
                if not words:
                    continue
                page_num = pn + 1
                # Название главы — собираем многострочный заголовок
                for ch in chapters:
                    if ch["page_start"] == page_num:
                        title_parts: List[str] = []
                        found_glava = False
                        for line in _group_lines(words):
                            text = _line_text(line)
                            size = _line_size(line)
                            if re.match(r"^\s*ГЛАВА\s+", text) and size >= 30:
                                found_glava = True
                                title_parts.append(re.sub(r"^\s*ГЛАВА\s+", "", text).strip())
                                continue
                            # Продолжаем собирать заголовок, пока строки крупные (size>=28)
                            if found_glava and size >= 28 and text:
                                # Пропускаем одиночные римские цифры (номер главы)
                                if re.fullmatch(r"[IVXLCivxlc]+", text.strip()):
                                    continue
                                # Главный вопрос параграфа — заголовок главы закончился
                                if text.strip().startswith("?"):
                                    break
                                title_parts.append(text.strip())
                            elif found_glava:
                                break
                        if title_parts:
                            ch["title"] = _normalize_title_case(" ".join(title_parts))
                        break
                # Текст параграфа
                para_num = page_para.get(page_num)
                if not para_num:
                    continue
                # Находим параграф в текущей главе
                target = None
                for ch in chapters:
                    if ch["page_start"] <= page_num <= ch["page_end"]:
                        for pr in ch["paragraphs"]:
                            if pr["number"] == para_num and pr["page_start"] <= page_num <= pr["page_end"]:
                                target = pr
                                break
                        break
                if target is None:
                    continue
                if "content" not in target:
                    target["content"] = []
                for line in _group_lines(words):
                    text = _line_text(line)
                    if not text:
                        continue
                    size = _line_size(line)
                    # Пропускаем колонтитулы (§ N, ГЛАВА N), заголовки (size>=18),
                    # номера страниц
                    if re.match(r"^\s*§\s*\d", text):
                        continue
                    if re.match(r"^\s*ГЛАВА\s+[IVXLC]+\s*$", text) and size < 18:
                        continue
                    if size >= 18:
                        continue
                    if re.match(r"^\s*\d{1,3}\s*$", text) and size >= 14:
                        continue
                    # Главный вопрос параграфа «? ...» — собираем из нескольких строк
                    if text.startswith("?") or collecting_question:
                        if not target.get("main_question"):
                            target["main_question"] = text.lstrip("?").strip()
                        else:
                            target["main_question"] += " " + text.strip()
                        collecting_question = not text.rstrip().endswith("?")
                        # Защита от зацикливания: вопрос не может быть длиннее 300 символов
                        if len(target.get("main_question", "")) > 300:
                            collecting_question = False
                        continue
                    collecting_question = False
                    # Убираем лишние «?» в конце вопроса (артефакты PDF)
                    if target.get("main_question"):
                        target["main_question"] = re.sub(r"\s*\?+\s*$", "?", target["main_question"]).strip()
                    # Врезки/словарь терминов «• ...»
                    if text.startswith("•"):
                        continue
                    # Подписи к иллюстрациям оставляем — они относятся к теме
                    # параграфа и могут содержать полезные факты (даты, события).
                    target["content"].append(text)

        # Сопоставляем с оглавлением: заполняем корректные названия глав и параграфов
        toc = self._extract_toc(pdf_path)
        toc_chapters = sorted(toc["chapters"], key=lambda c: c.get("page") or 0)
        toc_paras: Dict[str, str] = {}
        for p in toc["paragraphs"]:
            # Номер параграфа может быть диапазоном «2—3» — берём начальный номер
            start = re.split(r"[—–-]", p["number"])[0].strip()
            toc_paras.setdefault(start, p["title"])
        for ch in chapters:
            # Название главы из оглавления: сопоставляем по странице начала
            # (page_start парсера >= page главы в оглавлении, но ближайшая)
            best = None
            for tc in toc_chapters:
                if tc.get("page") and ch["page_start"] >= tc["page"]:
                    best = tc
                else:
                    break
            if best:
                ch["number"] = best["number"]
                ch["title"] = best["title"]
            for pr in ch["paragraphs"]:
                # Название параграфа из оглавления (по начальному номеру диапазона)
                start = re.split(r"[—–-]", pr["number"])[0].strip()
                if start in toc_paras:
                    pr["title"] = toc_paras[start]

        # Преобразуем в структуру параграфов
        result: List[Dict[str, Any]] = []
        for ch in chapters:
            new_ch = {"title": ch["title"], "number": ch["number"],
                      "page_start": ch["page_start"], "page_end": ch["page_end"],
                      "paragraphs": []}
            for pr in ch["paragraphs"]:
                para = _new_paragraph()
                para["number"] = pr["number"]
                para["title"] = pr.get("title", "")
                para["page_start"] = pr["page_start"]
                para["page_end"] = pr["page_end"]
                # Склеиваем перенесённые слова в тексте параграфа
                para["content"] = _join_hyphenated(pr.get("content", []))
                mq = pr.get("main_question", "")
                # Склеиваем перенесённые слова в вопросе («возник- новение» -> «возникновение»)
                mq = re.sub(r"([а-яё]+)-\s+([а-яё]+)", r"\1\2", mq) if mq else ""
                # Убираем повторяющиеся «?» в конце (артефакты PDF: «...экономику??» -> «...экономику?»)
                mq = re.sub(r"(?:\s*\?)+\s*$", "?", mq).strip()
                para["main_question"] = mq
                new_ch["paragraphs"].append(para)
            result.append(new_ch)

        logger.info("Vseobschaya_11.pdf: глав=%d, параграфов=%d",
                    len(result), sum(len(c["paragraphs"]) for c in result))
        return result

    def assign_chapter_numbers(self, chapters: List[Dict[str, Any]]) -> None:
        pass

    def extract_key_elements(self, paragraph: Dict[str, Any]) -> None:
        pass


class Parser11KlassRossiiPdf:
    """11 класс — История России (PDF).

    Структура:
      - Главы: «ГЛАВА НАЗВАНИЕ» (size=40) + номер «I» (size=40).
      - Параграфы: «§ N Название» (size=20) — явные заголовки в теле.
      - Колонтитулы: «ГЛАВА I» (size=13), «§ N. Название» (size=13).
      - Номера страниц: size=16.
    """

    is_pdf_parser = True

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.start_page = 6  # первая глава в теле

    def _extract_toc(self, pdf_path: str) -> Dict[str, Any]:
        """Извлекает оглавление (последние страницы): главы и параграфы с номерами и названиями.

        Возвращает:
            {"chapters": [{number, title, page}], "paragraphs": [{number, title, page}]}
        """
        chapters: List[Dict[str, Any]] = []
        paragraphs: List[Dict[str, Any]] = []
        cur: Dict[str, Any] | None = None
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            # Оглавление — на последних 2 страницах (447-448)
            toc_pages = [total - 2, total - 1]
            for pn in toc_pages:
                try:
                    words = pdf.pages[pn].extract_words(extra_attrs=["fontname", "size"])
                except Exception:
                    continue
                lines = [_line_text(l) for l in _group_lines(words)]
                lines = [l for l in lines if l]
                for text in lines:
                    # Глава «Глава I. Название»
                    m = re.match(r"^Глава\s+([IVXLC]+)\.\s*(.*)$", text)
                    if m:
                        if cur:
                            (chapters if cur["type"] == "chapter" else paragraphs).append(cur)
                        cur = {"type": "chapter", "number": m.group(1), "title": m.group(2).strip()}
                        pm = re.search(r"\.{3,}\s*(\d+)\s*$", text)
                        if pm:
                            cur["page"] = int(pm.group(1))
                        continue
                    # Параграф «§ N. Название»
                    m = re.match(r"^§\s*(\d+(?:[–-]\d+)?)\.?\s*(.*)$", text)
                    if m:
                        if cur:
                            (chapters if cur["type"] == "chapter" else paragraphs).append(cur)
                        cur = {"type": "paragraph", "number": m.group(1), "title": m.group(2).strip()}
                        pm = re.search(r"\.{3,}\s*(\d+)\s*$", text)
                        if pm:
                            cur["page"] = int(pm.group(1))
                        continue
                    # Продолжение многострочной записи
                    if cur and text and not re.match(
                        r"^(Вопросы|Темы|Ресурсы|Дополнительные|Заключение|Словарь|Основные|Интернет|Советуем|В учебнике|Полный|Иллюстративный|материалы|Российского|https)",
                        text,
                    ):
                        clean = re.sub(r"\s*\.{3,}\s*\d*\s*$", "", text).strip()
                        if clean:
                            cur["title"] += " " + clean
                        pm = re.search(r"\.{3,}\s*(\d+)\s*$", text)
                        if pm:
                            cur["page"] = int(pm.group(1))
        if cur:
            (chapters if cur["type"] == "chapter" else paragraphs).append(cur)

        # Очищаем названия от точек-заполнителей и номеров страниц
        for item in chapters + paragraphs:
            title = re.sub(r"\s*\.{3,}\s*\d*\s*$", "", item["title"]).strip()
            title = re.sub(r"\s+\d{1,3}\s*$", "", title).strip()
            item["title"] = title
        # Дополнительная очистка названий через LLM (убирает остаточный мусор)
        all_titles = [item["title"] for item in chapters + paragraphs]
        cleaned = _clean_titles_with_llm(all_titles)
        for item, title in zip(chapters + paragraphs, cleaned):
            item["title"] = title
        return {"chapters": chapters, "paragraphs": paragraphs}

    def parse_document(self, pdf_path: str) -> List[Dict[str, Any]]:
        chapters: List[Dict[str, Any]] = []
        current_chapter = None
        current_para = None
        collecting_question = False
        collecting_chapter_title = False
        collecting_para_title = False

        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            for pn in range(self.start_page - 1, total):
                page = pdf.pages[pn]
                try:
                    words = page.extract_words(extra_attrs=["fontname", "size"])
                except Exception:  # noqa: BLE001 — пропускаем проблемные страницы
                    logger.warning("Пропускаю проблемную страницу %d", pn + 1)
                    continue
                if not words:
                    continue
                page_num = pn + 1
                for line in _group_lines(words):
                    text = _line_text(line)
                    if not text:
                        continue
                    size = _line_size(line)

                    # Глава
                    m = re.match(r"^\s*ГЛАВА\s+(.+)$", text)
                    if m and size >= 30:
                        current_chapter = {
                            "title": m.group(1).strip(),
                            "number": "",
                            "page_start": page_num,
                            "page_end": page_num,
                            "paragraphs": [],
                        }
                        chapters.append(current_chapter)
                        current_para = None
                        collecting_question = False
                        collecting_chapter_title = True
                        collecting_para_title = False
                        continue
                    # Продолжаем собирать многострочный заголовок главы (size>=30)
                    if collecting_chapter_title and current_chapter:
                        if size >= 30 and text:
                            # Номер главы (римская цифра) — не часть названия
                            if re.fullmatch(r"[IVXLCivxlc]+", text.strip()):
                                current_chapter["number"] = text.strip()
                                continue
                            # Главный вопрос параграфа — заголовок главы закончился
                            if text.strip().startswith("?"):
                                collecting_chapter_title = False
                                continue
                            current_chapter["title"] += " " + text.strip()
                            continue
                        else:
                            collecting_chapter_title = False

                    # Параграф «§ N» (size>=18)
                    pm = re.match(r"^\s*§\s*(\d+(?:[–-]\d+)?)\s*(.*)$", text)
                    if pm and size >= 18 and current_chapter:
                        para = _new_paragraph()
                        para["number"] = pm.group(1)
                        para["title"] = pm.group(2).strip()
                        para["page_start"] = page_num
                        para["page_end"] = page_num
                        current_chapter["paragraphs"].append(para)
                        current_para = para
                        collecting_question = False
                        collecting_para_title = True
                        continue
                    # Продолжаем собирать многострочный заголовок параграфа (size>=18)
                    if collecting_para_title and current_para:
                        if size >= 18 and text:
                            current_para["title"] += " " + text.strip()
                            continue
                        else:
                            collecting_para_title = False

                    # Обычный текст
                    if current_para is None:
                        continue
                    # Пропускаем колонтитулы, номера страниц, заголовки (size>=18)
                    if re.match(r"^\s*§\s*\d", text) and size < 18:
                        continue
                    if re.match(r"^\s*ГЛАВА\s+[IVXLC]+\s*$", text) and size < 18:
                        continue
                    if re.match(r"^\s*\d{1,3}\s*$", text) and size >= 14:
                        continue
                    if size >= 18:
                        continue
                    # Главный вопрос параграфа «? ...» — собираем из нескольких строк
                    if text.startswith("?") or collecting_question:
                        if not current_para.get("main_question"):
                            current_para["main_question"] = text.lstrip("?").strip()
                        else:
                            current_para["main_question"] += " " + text.strip()
                        collecting_question = not text.rstrip().endswith("?")
                        # Защита от зацикливания: вопрос не может быть длиннее 300 символов
                        if len(current_para.get("main_question", "")) > 300:
                            collecting_question = False
                        continue
                    # Подписи к иллюстрациям оставляем — они относятся к теме
                    # параграфа и могут содержать полезные факты (даты, события).
                    current_para["content"].append(text)
                    current_para["page_end"] = page_num
                if current_chapter:
                    current_chapter["page_end"] = page_num

        # Финальная очистка: нормализация регистра, склейка переносов
        for ch in chapters:
            ch["title"] = _normalize_title_case(ch["title"])
            for pr in ch["paragraphs"]:
                pr["title"] = _normalize_title_case(pr["title"])
                pr["content"] = _join_hyphenated(pr.get("content", []))
                mq = pr.get("main_question", "")
                # Склеиваем перенесённые слова в вопросе («возник- новение» -> «возникновение»)
                mq = re.sub(r"([а-яё]+)-\s+([а-яё]+)", r"\1\2", mq) if mq else ""
                # Убираем повторяющиеся «?» в конце (артефакты PDF: «...экономику??» -> «...экономику?»)
                mq = re.sub(r"(?:\s*\?)+\s*$", "?", mq).strip()
                pr["main_question"] = mq

        # Сопоставляем с оглавлением (последние страницы) — корректные названия
        # глав и параграфов в нормальном регистре вместо Title Case из тела.
        toc = self._extract_toc(pdf_path)
        toc_chapters = toc["chapters"]
        toc_paragraphs = toc["paragraphs"]

        # Сопоставление глав по ближайшей странице начала
        for ch in chapters:
            best = None
            best_dist = None
            for tc in toc_chapters:
                if "page" not in tc:
                    continue
                dist = abs(ch["page_start"] - tc["page"])
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = tc
            if best and best_dist is not None and best_dist <= 3:
                ch["title"] = best["title"]
                if not ch.get("number"):
                    ch["number"] = best["number"]

        # Сопоставление параграфов по номеру
        toc_by_num: Dict[str, Dict[str, Any]] = {}
        for tp in toc_paragraphs:
            toc_by_num.setdefault(tp["number"], tp)
        for ch in chapters:
            for pr in ch["paragraphs"]:
                tp = toc_by_num.get(pr["number"])
                if tp and tp["title"]:
                    pr["title"] = tp["title"]

        logger.info("Istoriya_Rossii_11kl_2023.pdf: глав=%d, параграфов=%d",
                    len(chapters), sum(len(c["paragraphs"]) for c in chapters))
        return chapters

    def assign_chapter_numbers(self, chapters: List[Dict[str, Any]]) -> None:
        pass

    def extract_key_elements(self, paragraph: Dict[str, Any]) -> None:
        pass
