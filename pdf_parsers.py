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

import logging
import re
from typing import Any, Dict, List

import pdfplumber

logger = logging.getLogger("pdf_parsers")


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

    def parse_document(self, pdf_path: str) -> List[Dict[str, Any]]:
        chapters: List[Dict[str, Any]] = []
        page_para: Dict[int, str] = {}  # page_num -> номер параграфа
        page_header: Dict[int, bool] = {}  # page_num -> это заголовок параграфа?

        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            # Шаг 1: определяем параграф на каждой странице (по колонтитулу/заголовку)
            for pn in range(self.start_page - 1, total):
                page = pdf.pages[pn]
                words = page.extract_words(extra_attrs=["fontname", "size"])
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
                page = pdf.pages[pn]
                words = page.extract_words(extra_attrs=["fontname", "size"])
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
                page = pdf.pages[pn]
                words = page.extract_words(extra_attrs=["fontname", "size"])
                if not words:
                    continue
                page_num = pn + 1
                # Название главы
                for ch in chapters:
                    if ch["page_start"] == page_num:
                        for line in _group_lines(words):
                            text = _line_text(line)
                            size = _line_size(line)
                            if re.match(r"^\s*ГЛАВА\s+", text) and size >= 30:
                                ch["title"] = re.sub(r"^\s*ГЛАВА\s+", "", text).strip()
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

        # Преобразуем в структуру параграфов
        result: List[Dict[str, Any]] = []
        for ch in chapters:
            new_ch = {"title": ch["title"], "number": ch["number"],
                      "page_start": ch["page_start"], "page_end": ch["page_end"],
                      "paragraphs": []}
            for pr in ch["paragraphs"]:
                para = _new_paragraph()
                para["number"] = pr["number"]
                para["page_start"] = pr["page_start"]
                para["page_end"] = pr["page_end"]
                para["content"] = pr.get("content", [])
                mq = pr.get("main_question", "")
                # Финальная очистка: убираем лишние «?» в конце вопроса
                mq = re.sub(r"\s*\?+\s*$", "?", mq).strip()
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

    def parse_document(self, pdf_path: str) -> List[Dict[str, Any]]:
        chapters: List[Dict[str, Any]] = []
        current_chapter = None
        current_para = None
        collecting_question = False

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
                        continue
                    # Номер главы (римская цифра, size>=30)
                    if current_chapter and size >= 30 and re.match(r"^\s*[IVXLC]+\s*$", text):
                        current_chapter["number"] = text.strip()
                        continue

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
                        continue

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

        # Финальная очистка main_question: убираем лишние «?» в конце
        for ch in chapters:
            for pr in ch["paragraphs"]:
                mq = pr.get("main_question", "")
                pr["main_question"] = re.sub(r"\s*\?+\s*$", "?", mq).strip()

        logger.info("Istoriya_Rossii_11kl_2023.pdf: глав=%d, параграфов=%d",
                    len(chapters), sum(len(c["paragraphs"]) for c in chapters))
        return chapters

    def assign_chapter_numbers(self, chapters: List[Dict[str, Any]]) -> None:
        pass

    def extract_key_elements(self, paragraph: Dict[str, Any]) -> None:
        pass
