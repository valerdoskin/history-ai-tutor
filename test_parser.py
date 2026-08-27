# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки работы парсеров учебников истории.

Проверяет работу DOCX- и PDF-парсеров на реальном учебнике:
  - корректность определения глав и параграфов;
  - извлечение главного вопроса;
  - извлечение разделов;
  - извлечение специальных блоков;
  - извлечение ключевых элементов (даты, термины, персоналии);
  - фильтрацию подписей к иллюстрациям.

Использование:
    python test_parser.py [--docx books/6_klass._Istoriya_Rossii.docx]
                           [--pdf books/6_klass._Istoriya_Rossii.pdf]
                           [--config config_russia_history.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import pdfplumber

from parser import (
    detect_special_block,
    extract_dates,
    extract_figures_from_words,
    extract_terms_from_words,
    group_words_into_lines,
    is_bold,
    is_bold_italic,
    is_italic,
    line_formatting,
    line_to_text,
    load_config,
    parse_textbook as parse_pdf_textbook,
)

from docx_parser import (
    extract_figures_from_runs,
    extract_terms_from_runs,
    is_caption_paragraph,
    is_caption_text,
    parse_textbook as parse_docx_textbook,
)

# ---------------------------------------------------------------------------
# Настройка логирования
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_parser")

# Количество проверок и пройденных проверок
PASSED = 0
FAILED = 0


def check(condition: bool, message: str) -> None:
    """Проверяет условие и выводит результат."""
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {message}")
    else:
        FAILED += 1
        print(f"  ❌ {message}")


def test_font_detection() -> None:
    """Проверяет определение форматирования по имени шрифта."""
    print("\n[1] Проверка определения форматирования шрифта")
    check(is_bold("TextbookNSanPin-Bold"), "is_bold('TextbookNSanPin-Bold') == True")
    check(not is_bold("TextbookNSanPin-Regular"), "is_bold('TextbookNSanPin-Regular') == False")
    check(is_italic("TextbookNSanPin-Italic"), "is_italic('TextbookNSanPin-Italic') == True")
    check(is_bold_italic("TextbookNSanPin-BoldItalic"), "is_bold_italic('TextbookNSanPin-BoldItalic') == True")
    check(not is_bold_italic("TextbookNSanPin-Italic"), "is_bold_italic('TextbookNSanPin-Italic') == False")


def test_date_extraction() -> None:
    """Проверяет извлечение дат из текста."""
    print("\n[2] Проверка извлечения дат")
    text = "В 911 г. Игорь погиб. В 945—964 гг. правила Ольга. В VII в. началось переселение."
    dates = extract_dates(text)
    check("911 г." in dates, "Найдена дата '911 г.'")
    check("945—964 гг." in dates, "Найдена дата '945—964 гг.'")
    check("VII в." in dates, "Найдена дата 'VII в.'")


def test_special_block_detection() -> None:
    """Проверяет определение специальных блоков."""
    print("\n[3] Проверка определения специальных блоков")
    config = load_config("config_russia_history.json")
    special_blocks = config["special_blocks"]

    check(detect_special_block("иСторичеСкий портрет", special_blocks) == "historical_portrait",
          "Определён блок 'иСторичеСкий портрет'")
    check(detect_special_block("СвидетельСтво эпохи", special_blocks) == "witness_of_epoch",
          "Определён блок 'СвидетельСтво эпохи'")
    check(detect_special_block("Работаем с ХРОнОЛОГиеЙ", special_blocks) == "work_with_chronology",
          "Определён блок 'Работаем с ХРОнОЛОГиеЙ'")
    check(detect_special_block("ПОдВедЁМ иТОГи", special_blocks) == "summary",
          "Определён блок 'ПОдВедЁМ иТОГи'")
    check(detect_special_block("Обычный текст", special_blocks) is None,
          "Обычный текст не определён как спецблок")


def test_parse_single_paragraph(pdf_path: str, config_path: str) -> None:
    """
    Проверяет парсинг одного параграфа реального учебника.

    Обрабатывает первые несколько страниц и проверяет структуру.
    """
    print("\n[4] Проверка парсинга реального учебника")
    config = load_config(config_path)

    with pdfplumber.open(pdf_path) as pdf:
        # Обрабатываем первые 15 страниц (достаточно для первого параграфа)
        chapters: List[Dict[str, Any]] = []
        from parser import parse_page
        for page_num in range(1, min(16, len(pdf.pages) + 1)):
            parse_page(pdf.pages[page_num - 1], page_num, config, chapters)

        check(len(chapters) >= 1, f"Найдена хотя бы одна глава (найдено: {len(chapters)})")

        if chapters:
            chapter = chapters[0]
            check(len(chapter["paragraphs"]) >= 1,
                  f"В главе найден хотя бы один параграф (найдено: {len(chapter['paragraphs'])})")

            if chapter["paragraphs"]:
                para = chapter["paragraphs"][0]
                check(para["title"] != "", "Параграф имеет заголовок")
                check(para["page_start"] is not None, "Параграф имеет номер начальной страницы")
                print(f"  📄 Заголовок параграфа: {para['title']}")
                print(f"  📄 Страницы: {para['page_start']}–{para['page_end']}")
                if para["main_question"]:
                    print(f"  ❓ Главный вопрос: {para['main_question'][:80]}...")
                if para["sections"]:
                    print(f"  📑 Разделов: {len(para['sections'])}")
                    for sec in para["sections"][:3]:
                        print(f"     - {sec['number']}. {sec['title']}")
                if para["special_blocks"]:
                    print(f"  📦 Спецблоков: {list(para['special_blocks'].keys())}")
                if para["key_elements"]["dates"]:
                    print(f"  📅 Даты: {para['key_elements']['dates'][:5]}")
                if para["key_elements"]["terms"]:
                    print(f"  📖 Термины: {para['key_elements']['terms'][:5]}")
                if para["key_elements"]["figures"]:
                    print(f"  👤 Персоналии: {para['key_elements']['figures'][:5]}")


def test_full_parse(pdf_path: str, config_path: str) -> None:
    """
    Проверяет полный парсинг PDF-учебника (без сохранения в файл).

    Запускает parse_textbook и проверяет итоговую статистику.
    """
    print("\n[5] Проверка полного парсинга PDF-учебника")
    try:
        result = parse_pdf_textbook(pdf_path, config_path, "/tmp/test_parser_output.json")
        check(result["total_chapters"] > 0, f"Найдены главы: {result['total_chapters']}")
        check(result["total_paragraphs"] > 0, f"Найдены параграфы: {result['total_paragraphs']}")
        print(f"  📊 Итог: глав {result['total_chapters']}, параграфов {result['total_paragraphs']}")
    except Exception as exc:  # noqa: BLE001
        check(False, f"Ошибка при полном парсинге: {exc}")


def test_caption_filtering() -> None:
    """Проверяет фильтрацию подписей к иллюстрациям."""
    print("\n[6] Проверка фильтрации подписей к иллюстрациям")

    # Подписи, начинающиеся с маркера
    check(is_caption_paragraph("Памятник Дмитрию Донскому в Москве"),
          "Подпись 'Памятник...' определена")
    check(is_caption_paragraph("Художник А. Кившенко"),
          "Подпись 'Художник...' определена")
    check(is_caption_paragraph("Миниатюра из Лицевого летописного свода"),
          "Подпись 'Миниатюра...' определена")
    check(is_caption_paragraph("Государственная оружейная палата. Москва"),
          "Подпись 'Государственная оружейная палата...' определена")
    # Подпись, где маркер в курсивной части (передаём runs)
    runs = [
        {"text": "Батый.", "bold": True, "italic": False},
        {"text": "С китайского рисунка XIII в.", "bold": False, "italic": True},
    ]
    check(is_caption_paragraph("Батый. С китайского рисунка XIII в.", runs),
          "Подпись 'Батый. С китайского рисунка...' определена")

    # Подписи, где маркер в курсивной части
    runs = [
        {"text": "Отправка Марфы Посадницы", "bold": True, "italic": False},
        {"text": "Художник А. Кившенко", "bold": False, "italic": True},
    ]
    check(is_caption_paragraph("Отправка Марфы Посадницы", runs),
          "Подпись с маркером в курсивной части определена")

    # Обычный текст не должен определяться как подпись
    check(not is_caption_paragraph("Великое переселение народов"),
          "Обычный текст не определён как подпись")
    check(not is_caption_paragraph("Как образовалось государство Русь?"),
          "Вопрос не определён как подпись")


def test_docx_key_elements() -> None:
    """Проверяет извлечение ключевых элементов из runs DOCX."""
    print("\n[7] Проверка извлечения ключевых элементов из runs")

    # Термины — курсивные слова
    runs = [
        {"text": "тюрки", "bold": False, "italic": True},
        {"text": "славяне", "bold": False, "italic": True},
        {"text": "обычный текст", "bold": False, "italic": False},
        {"text": "XIII", "bold": False, "italic": True},  # римская цифра — не термин
        {"text": "1480", "bold": False, "italic": True},  # число — не термин
    ]
    terms = extract_terms_from_runs(runs)
    check("тюрки" in terms, "Термин 'тюрки' извлечён")
    check("славяне" in terms, "Термин 'славяне' извлечён")
    check("XIII" not in terms, "Римская цифра 'XIII' не извлечена как термин")
    check("1480" not in terms, "Число '1480' не извлечено как термин")

    # Персоналии — полужирный курсив
    runs = [
        {"text": "Рюрика", "bold": True, "italic": True},
        {"text": "Олег", "bold": True, "italic": True},
        {"text": "обычный текст", "bold": False, "italic": False},
    ]
    figures = extract_figures_from_runs(runs)
    check("Рюрика" in figures, "Персоналия 'Рюрика' извлечена")
    check("Олег" in figures, "Персоналия 'Олег' извлечена")


def test_docx_full_parse(docx_path: str, config_path: str) -> None:
    """
    Проверяет полный парсинг DOCX-учебника.

    Запускает parse_textbook из docx_parser и проверяет итоговую статистику,
    а также отсутствие артефактов и подписей к иллюстрациям в терминах.
    """
    print("\n[8] Проверка полного парсинга DOCX-учебника")
    try:
        result = parse_docx_textbook(docx_path, config_path, "/tmp/test_docx_output.json")
        check(result["total_chapters"] > 0, f"Найдены главы: {result['total_chapters']}")
        check(result["total_paragraphs"] > 0, f"Найдены параграфы: {result['total_paragraphs']}")
        print(f"  📊 Итог: глав {result['total_chapters']}, параграфов {result['total_paragraphs']}")

        # Проверяем отсутствие артефактов и подписей в терминах
        all_terms: List[str] = []
        for ch in result["data"]:
            for p in ch["paragraphs"]:
                all_terms.extend(p["key_elements"]["terms"])

        # Артефакт \uf401 не должен встречаться
        artifact_terms = [t for t in all_terms if "\uf401" in t]
        check(len(artifact_terms) == 0, "Нет артефактов \\uf401 в терминах")

        # Подписи к иллюстрациям не должны попадать в термины
        caption_terms = [t for t in all_terms if is_caption_text(t)]
        check(len(caption_terms) == 0, "Нет подписей к иллюстрациям в терминах")

        # Римские цифры (века) не должны попадать в термины
        import re
        roman_terms = [t for t in all_terms if re.match(r"^[IVXLCDM]+$", t.strip())]
        check(len(roman_terms) == 0, "Нет римских цифр в терминах")

        # Проверяем, что у каждого параграфа есть заголовок
        empty_titles = [p for ch in result["data"] for p in ch["paragraphs"] if not p["title"]]
        check(len(empty_titles) == 0, "Все параграфы имеют заголовки")

        # Проверяем, что у каждого параграфа есть главный вопрос
        empty_questions = [p for ch in result["data"] for p in ch["paragraphs"] if not p["main_question"]]
        check(len(empty_questions) == 0, "Все параграфы имеют главный вопрос")

    except Exception as exc:  # noqa: BLE001
        check(False, f"Ошибка при полном парсинге DOCX: {exc}")


def main() -> None:
    """Точка входа в тестовый скрипт."""
    parser = argparse.ArgumentParser(description="Тест парсеров учебников истории")
    parser.add_argument(
        "--docx",
        default="books/6_klass._Istoriya_Rossii.docx",
        help="Путь к DOCX-учебнику для теста",
    )
    parser.add_argument(
        "--pdf",
        default="books/6_klass._Istoriya_Rossii.pdf",
        help="Путь к PDF-учебнику для теста",
    )
    parser.add_argument(
        "--config",
        default="config_russia_history.json",
        help="Путь к конфигурационному файлу",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Выполнить полный парсинг учебника (может занять время)",
    )
    args = parser.parse_args()

    if not Path(args.docx).exists():
        logger.error("DOCX-файл не найден: %s", args.docx)
        sys.exit(1)
    if not Path(args.pdf).exists():
        logger.error("PDF-файл не найден: %s", args.pdf)
        sys.exit(1)
    if not Path(args.config).exists():
        logger.error("Конфигурация не найдена: %s", args.config)
        sys.exit(1)

    print("=" * 60)
    print("ТЕСТ ПАРСЕРОВ УЧЕБНИКОВ ИСТОРИИ")
    print("=" * 60)
    print(f"DOCX: {args.docx}")
    print(f"PDF: {args.pdf}")
    print(f"Конфигурация: {args.config}")

    test_font_detection()
    test_date_extraction()
    test_special_block_detection()
    test_caption_filtering()
    test_docx_key_elements()
    test_parse_single_paragraph(args.pdf, args.config)

    if args.full:
        test_full_parse(args.pdf, args.config)
        test_docx_full_parse(args.docx, args.config)

    print("\n" + "=" * 60)
    print(f"ИТОГ: пройдено {PASSED}, не пройдено {FAILED}")
    print("=" * 60)

    if FAILED > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
