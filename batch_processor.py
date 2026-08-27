# -*- coding: utf-8 -*-
"""
Пакетный обработчик учебников истории (DOCX/PDF → единый JSON).

Скрипт обрабатывает все DOCX- и PDF-файлы из папки books/, автоматически
подбирая конфигурацию (история России или всеобщая история) по имени
файла, и сохраняет результаты в единый JSON-файл с отчётом.

Формат файла определяется по расширению:
  - .docx — используется docx_parser (основной парсер);
  - .pdf  — используется parser (PDF-парсер, fallback для будущих файлов).

Использование:
    python batch_processor.py [--books-dir books] [--output output.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from base_docx_parser import BaseDocxParser, load_config
from parser import parse_textbook as parse_pdf_textbook
from parsers import get_parser_for_file

# ---------------------------------------------------------------------------
# Настройка логирования
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("batch_processor")

# ---------------------------------------------------------------------------
# Конфигурация по умолчанию
# ---------------------------------------------------------------------------
# Ключевые слова для определения линейки учебника по имени файла
RUSSIA_KEYWORDS = ["istoriya_rossii", "rossii", "russia"]
WORLD_KEYWORDS = ["vseobschaya", "vseobshchaya", "world", "drevnego", "za_"]

# Конфигурационные файлы
CONFIG_RUSSIA = "config_russia_history.json"
CONFIG_WORLD = "config_world_history.json"


def detect_config(filename: str) -> str:
    """
    Определяет, какой конфигурационный файл использовать для учебника.

    По имени файла определяет линейку: история России или всеобщая история.
    """
    name = filename.lower()
    for kw in RUSSIA_KEYWORDS:
        if kw in name:
            return CONFIG_RUSSIA
    for kw in WORLD_KEYWORDS:
        if kw in name:
            return CONFIG_WORLD
    # По умолчанию — всеобщая история
    return CONFIG_WORLD


def process_book(
    book_path: Path,
    config_path: Path,
    output_dir: Path,
) -> Dict[str, Any]:
    """
    Обрабатывает один учебник (DOCX или PDF).

    Формат определяется по расширению файла:
      - .docx — используется docx_parser (основной парсер);
      - .pdf  — используется PDF-парсер (fallback).

    Возвращает словарь с результатами обработки (метаданные + данные).
    """
    logger.info("=" * 60)
    logger.info("Обработка: %s", book_path.name)
    logger.info("Конфигурация: %s", config_path.name)

    # Имя выходного файла для отдельного учебника
    book_output = output_dir / f"{book_path.stem}.json"

    # Выбираем парсер по расширению файла
    ext = book_path.suffix.lower()
    if ext == ".docx":
        fmt = "docx"
        # Выбираем специализированный парсер по имени файла.
        # Если совпадения нет — используем базовый парсер.
        registry_entry = get_parser_for_file(book_path.name)
        if registry_entry:
            parser_cls = registry_entry["parser"]
            config_name = registry_entry["config"]
            logger.info("Парсер: %s (конфигурация: %s)",
                        parser_cls.__name__, config_name)
        else:
            parser_cls = BaseDocxParser
            config_name = config_path.name
            logger.info("Парсер: %s (конфигурация: %s)",
                        parser_cls.__name__, config_name)
        config = load_config(config_name)
        parser = parser_cls(config)
        parse_func = lambda p, c, o: parser.parse_textbook(p, o)  # noqa: E731
    elif ext == ".pdf":
        parse_func = parse_pdf_textbook
        fmt = "pdf"
    else:
        logger.error("Неподдерживаемый формат файла: %s", book_path.name)
        return {
            "file": book_path.name,
            "config": config_path.name,
            "format": ext,
            "status": "error",
            "error": f"Неподдерживаемый формат: {ext}",
        }

    try:
        result = parse_func(str(book_path), str(config_path), str(book_output))
        logger.info("Успешно обработан: %s (глав: %d, параграфов: %d)",
                    book_path.name, result["total_chapters"], result["total_paragraphs"])
        return {
            "file": book_path.name,
            "config": config_path.name,
            "format": fmt,
            "status": "ok",
            "total_chapters": result["total_chapters"],
            "total_paragraphs": result["total_paragraphs"],
            "output_file": str(book_output),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("Ошибка при обработке %s: %s", book_path.name, exc)
        return {
            "file": book_path.name,
            "config": config_path.name,
            "format": fmt,
            "status": "error",
            "error": str(exc),
        }


def main() -> None:
    """Точка входа в скрипт."""
    parser = argparse.ArgumentParser(
        description="Пакетная обработка учебников истории (DOCX/PDF → JSON)"
    )
    parser.add_argument(
        "--books-dir",
        default="books",
        help="Папка с DOCX/PDF-учебниками (по умолчанию: books)",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Папка для результатов (по умолчанию: output)",
    )
    parser.add_argument(
        "--report",
        default="report.json",
        help="Имя файла отчёта (по умолчанию: report.json)",
    )
    args = parser.parse_args()

    books_dir = Path(args.books_dir)
    output_dir = Path(args.output)

    if not books_dir.exists():
        logger.error("Папка с учебниками не найдена: %s", books_dir)
        sys.exit(1)

    # Создаём папку для результатов
    output_dir.mkdir(parents=True, exist_ok=True)

    # Собираем все DOCX- и PDF-файлы (DOCX — основной формат, PDF — fallback).
    # PDF обрабатывается только для книг, у которых нет DOCX-версии.
    docx_files = sorted(books_dir.glob("*.docx"))
    pdf_files = sorted(books_dir.glob("*.pdf"))

    # Имена книг (без расширения), для которых уже есть DOCX-версия
    docx_stems = {f.stem for f in docx_files}

    # PDF-файлы, для которых нет соответствующего DOCX (fallback)
    fallback_pdf_files = [f for f in pdf_files if f.stem not in docx_stems]

    book_files = docx_files + fallback_pdf_files

    if not book_files:
        logger.error("В папке %s не найдено DOCX/PDF-файлов", books_dir)
        sys.exit(1)

    logger.info("Найдено файлов: %d (DOCX: %d, PDF-fallback: %d, PDF пропущено: %d)",
                len(book_files), len(docx_files), len(fallback_pdf_files),
                len(pdf_files) - len(fallback_pdf_files))

    # Обрабатываем каждый файл
    results: List[Dict[str, Any]] = []
    for book_file in book_files:
        config_name = detect_config(book_file.name)
        config_path = Path(config_name)
        if not config_path.exists():
            logger.error("Конфигурация не найдена: %s", config_name)
            results.append({
                "file": book_file.name,
                "config": config_name,
                "status": "error",
                "error": f"Конфигурация не найдена: {config_name}",
            })
            continue
        results.append(process_book(book_file, config_path, output_dir))

    # Формируем отчёт
    ok_count = sum(1 for r in results if r["status"] == "ok")
    error_count = sum(1 for r in results if r["status"] == "error")

    report = {
        "total_files": len(results),
        "ok": ok_count,
        "errors": error_count,
        "results": results,
    }

    report_path = output_dir / args.report
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info("=" * 60)
    logger.info("Обработка завершена: успешно %d, ошибок %d", ok_count, error_count)
    logger.info("Отчёт сохранён: %s", report_path)


if __name__ == "__main__":
    main()
