# -*- coding: utf-8 -*-
"""
Пересоздание базы знаний (chunks.json) из DOCX-учебников.

Парсит все DOCX-файлы из books/ через специализированные парсеры,
собирает полный текст каждого параграфа (включая разделы и спецблоки),
удаляет переносы "-" внутри слов и формирует chunks.json.

Использование:
    python rebuild_knowledge.py [--books-dir books] [--output knowledge/chunks.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from parsers import get_parser_for_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rebuild_knowledge")

# Максимальная длина текста одного чанка (как в исходной базе знаний)
CHUNK_MAX_CHARS = 1200


def fix_hyphenation(text: str) -> str:
    """Удаляет переносы "-" на новую строку внутри слов.

    Паттерн: буква + "-" + пробел + буква (перенос слова на новую строку).
    Дефисы в составных словах (без пробела) не трогаем.
    """
    return re.sub(r"([а-яёА-ЯЁa-zA-Z])-\s+([а-яёА-ЯЁa-zA-Z])", r"\1\2", text)


def build_paragraph_text(paragraph: Dict[str, Any]) -> str:
    """Собирает полный текст параграфа из всех его частей."""
    parts: List[str] = []

    # Главный вопрос
    mq = (paragraph.get("main_question") or "").strip()
    if mq:
        parts.append(f"Главный вопрос параграфа: {mq}")

    # Основной текст (ключевые слова, персоналии, текст)
    for c in paragraph.get("content", []):
        if c and c.strip():
            parts.append(c.strip())

    # Разделы
    for s in paragraph.get("sections", []):
        title = (s.get("title") or "").strip()
        if title:
            parts.append(title)
        for c in s.get("content", []):
            if c and c.strip():
                parts.append(c.strip())

    # Спецблоки (вопросы, хронология, источник и т.д.)
    for blocks in paragraph.get("special_blocks", {}).values():
        for b in blocks:
            header = (b.get("header") or "").strip()
            if header:
                parts.append(header)
            for c in b.get("content", []):
                if c and c.strip():
                    parts.append(c.strip())

    return "\n".join(parts)


def split_into_chunks(text: str, max_chars: int = CHUNK_MAX_CHARS) -> List[str]:
    """Разбивает текст параграфа на чанки по ~max_chars символов.

    Старается разрывать по границам абзацев (\n) или предложений.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    remaining = text
    while len(remaining) > max_chars:
        # Ищем границу разрыва: последний \n или ". " в пределах max_chars
        window = remaining[:max_chars]
        cut = -1
        # Ищем последний перенос строки
        nl = window.rfind("\n")
        if nl > max_chars * 0.5:
            cut = nl
        else:
            # Ищем конец предложения
            for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
                idx = window.rfind(sep)
                if idx > max_chars * 0.5:
                    cut = idx + len(sep)
                    break
        if cut <= 0:
            # Не нашли хорошую границу — режем по символам
            cut = max_chars
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def process_book(book_path: Path) -> List[Dict[str, Any]]:
    """Обрабатывает один DOCX-учебник и возвращает список чанков."""
    logger.info("Обработка: %s", book_path.name)

    # Выбираем специализированный парсер по имени файла
    registry_entry = get_parser_for_file(book_path.name)
    if registry_entry:
        parser_cls = registry_entry["parser"]
        config_name = registry_entry["config"]
    else:
        from base_docx_parser import BaseDocxParser

        parser_cls = BaseDocxParser
        config_name = "config_world_history.json"
        logger.warning("Нет специализированного парсера для %s, использую базовый", book_path.name)

    from base_docx_parser import load_config

    config = load_config(config_name)
    parser = parser_cls(config)

    # Парсим документ
    from docx import Document

    doc = Document(str(book_path))
    chapters = parser.parse_document(doc)
    parser.assign_chapter_numbers(chapters)
    for chapter in chapters:
        for paragraph in chapter["paragraphs"]:
            parser.extract_key_elements(paragraph)

    book_id = config["book_id"]
    book_line = config["book_line"]
    source_file = book_path.name

    chunks: List[Dict[str, Any]] = []
    for chapter in chapters:
        chapter_title = chapter.get("title", "")
        chapter_number = chapter.get("number", "")
        for paragraph in chapter["paragraphs"]:
            para_title = paragraph.get("title", "")
            para_number = paragraph.get("number", "")
            page_start = paragraph.get("page_start")
            page_end = paragraph.get("page_end")
            main_question = paragraph.get("main_question", "")

            full_text = build_paragraph_text(paragraph)
            full_text = fix_hyphenation(full_text)
            if not full_text.strip():
                continue

            text_chunks = split_into_chunks(full_text)
            total = len(text_chunks)
            for i, tc in enumerate(text_chunks):
                chunk_id = f"{book_id}::{chapter_number}::{para_title}::{i}"
                chunks.append({
                    "id": chunk_id,
                    "book_id": book_id,
                    "book_line": book_line,
                    "source_file": source_file,
                    "chapter_title": chapter_title,
                    "chapter_number": chapter_number,
                    "paragraph_title": para_title,
                    "paragraph_number": para_number,
                    "page_start": page_start,
                    "page_end": page_end,
                    "main_question": main_question,
                    "chunk_index": i,
                    "chunk_total": total,
                    "text": tc,
                    "metadata": {},
                })

    logger.info("Готово: %s — %d чанков", book_path.name, len(chunks))
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Пересоздание базы знаний из DOCX")
    parser.add_argument("--books-dir", default="books", help="Папка с DOCX-учебниками")
    parser.add_argument("--output", default="knowledge/chunks.json", help="Выходной файл chunks.json")
    parser.add_argument("--only", default="", help="Обработать только файлы, содержащие эту подстроку")
    args = parser.parse_args()

    books_dir = Path(args.books_dir)
    if not books_dir.exists():
        logger.error("Папка с учебниками не найдена: %s", books_dir)
        sys.exit(1)

    docx_files = sorted(books_dir.glob("*.docx"))
    if args.only:
        docx_files = [f for f in docx_files if args.only.lower() in f.name.lower()]
        if not docx_files:
            logger.error("Нет DOCX-файлов, содержащих '%s'", args.only)
            sys.exit(1)

    all_chunks: List[Dict[str, Any]] = []
    for book_path in docx_files:
        try:
            all_chunks.extend(process_book(book_path))
        except Exception as exc:  # noqa: BLE001
            logger.error("Ошибка при обработке %s: %s", book_path.name, exc)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)

    logger.info("Итого чанков: %d, сохранено в %s", len(all_chunks), output_path)


if __name__ == "__main__":
    main()
