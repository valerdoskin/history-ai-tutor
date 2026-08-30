"""
Специализированные парсеры для каждой книги.

Единая основа — BaseDocxParser (base_docx_parser.py). Здесь переопределяются
только те методы, которые отличаются для конкретной книги. Это позволяет
не ломать логику для ранее обработанных книг при доработке универсального
парсера.

Реестр парсеров (PARSER_REGISTRY) используется batch_processor.py для выбора
парсера по имени файла.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from base_docx_parser import (
    BaseDocxParser,
    paragraph_runs,
    _is_year_range,
)
from pdf_parsers import (
    Parser11KlassVseobschayaPdf,
    Parser11KlassRossiiPdf,
)


def _is_uppercase_title(text: str) -> bool:
    """Определяет, является ли текст названием главы (в основном заглавными).

    Названия глав в учебниках набраны прописными буквами, а подписи
    к иллюстрациям и эпиграфы — обычным (смешанным) регистром. Если
    большинство букв — заглавные, считаем текст частью названия главы.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) > 0.5


class Parser5Klass(BaseDocxParser):
    """5 класс — История Древнего мира.

    Структура глав:
      - «Г Л А В А» (Normal) → название главы (Heading 2 или Normal).
      - Номер главы (Heading 1) присутствует только у части глав.
    Базовая логика справляется полностью, переопределений не требуется.
    """


class Parser6KlassVseobschaya(BaseDocxParser):
    """6 класс — Всеобщая история.

    Структура глав:
      - «Г Л А В А» (Normal) → номер (Heading 1) → название (Normal).
    Базовая логика справляется полностью, переопределений не требуется.
    """


class Parser7KlassRossii(BaseDocxParser):
    """7 класс — История России.

    Структура глав:
      - «Г Л А В А» (Normal) → номер (Heading 1) → название (Heading 2).
    Базовая логика справляется полностью, переопределений не требуется.
    """


class Parser7KlassVseobschaya(Parser7KlassRossii):
    """7 класс — Всеобщая история.

    Структура глав та же, что и в 7 классе России, но есть особенность:
    буквы-обозначения карт (например, «D») оформлены как Heading 3 и
    ошибочно распознаются как начало параграфа. Настоящие параграфы —
    Heading 2 с «§ N Название». Поэтому Heading 3 с коротким текстом
    (одна буква) не считается началом параграфа.
    """

    def is_paragraph_heading(self, paragraph) -> bool:
        """Проверяет, является ли параграф заголовком параграфа (§).

        Настоящие параграфы — Heading 2 с «§». Heading 3 с коротким
        текстом (одна буква) — это буква-обозначение карты, а не
        начало параграфа.
        """
        text = paragraph.text.strip()
        # «иТоГи ГЛАВы» — это итоги главы, а не параграф
        if re.match(r"^иТоГи\s+ГЛАВы", text, re.IGNORECASE):
            return False
        # Heading 3 с коротким текстом (одна буква) — обозначение карты
        if paragraph.style.name == "Heading 3" and len(text) <= 3:
            return False
        # Настоящие параграфы — Heading 2 с «§»
        if paragraph.style.name == "Heading 2" and text.startswith("§"):
            return True
        return False


class Parser6KlassRossii(BaseDocxParser):
    """6 класс — История России.

    Особенность структуры глав (неоднородная внутри книги):
      - Глава I: название в двух Normal-параграфах, затем Heading 2 —
        это заголовок раздела (НЕ часть названия главы).
      - Главы III, IV: название начинается с Heading 2 и продолжается
        Normal-параграфом.

    Правило для этой книги:
      - Если название главы уже собрано (есть текст) и встречается
        Heading 2 — это заголовок раздела, сбор названия завершаем
        без добавления.
      - Если название главы пустое и встречается Heading 2 — это начало
        названия главы, добавляем и продолжаем сбор (не завершаем).
    """

    def collect_chapter_title(self, paragraph, text, current_chapter,
                              collecting_chapter_name, collecting_chapter_title,
                              pending_paragraph_number) -> str:
        # Заголовок параграфа (§) или Heading 2 с ожидаемым номером
        # параграфа — название главы закончилось.
        if self.is_paragraph_heading(paragraph) or (
            pending_paragraph_number and paragraph.style.name == "Heading 2"
        ):
            return "paragraph"
        # Подписи, главный вопрос, эпиграфы и «шум» — пропускаем.
        if self.is_caption_paragraph(text, paragraph_runs(paragraph)):
            return "skip"
        if "?" in text:
            return "skip"
        if text.startswith("«"):
            return "skip"
        runs = paragraph_runs(paragraph)
        if runs and any(r.get("bold") for r in runs) and any(r.get("italic") for r in runs):
            return "skip"
        # В этой книге названия глав не выделены жирным, а подписи
        # к иллюстрациям — жирные (например, «Мемориал ...»). Поэтому
        # жирный параграф — это подпись, пропускаем его.
        if runs and any(r.get("bold") for r in runs):
            return "skip"
        # Если название уже собрано и встретился Heading 2 — это заголовок
        # раздела, а не часть названия главы. Завершаем сбор без добавления.
        if current_chapter["title"] and paragraph.style.name == "Heading 2":
            return "skip"
        # Добавляем текст к названию главы.
        if current_chapter["title"]:
            current_chapter["title"] += " " + text
        else:
            current_chapter["title"] = text
        # В этой книге Heading 2 может быть началом названия главы,
        # поэтому не завершаем сбор на Heading 2 — продолжаем собирать
        # продолжение (Normal-параграфы).
        return "add"


class Parser8KlassVseobschaya(BaseDocxParser):
    """8 класс — Всеобщая история.

    Структура глав:
      - «Г Л А В А» (Normal) → название главы, разбитое на несколько
        параграфов (Normal + Heading 1 + Normal) в разном порядке.
      - Номера глав (римские цифры) отсутствуют — Heading 1 является
        частью названия главы, а не номером.
      - Параграфы: [Heading 2] § Название (без номера).

    Правило для этой книги:
      - Heading 1 не считается номером главы (is_chapter_number → False),
        поэтому он попадает в название главы.
      - Название собирается из Normal + Heading 1 + Normal и завершается
        на первом параграфе (§).
    """

    def is_chapter_number(self, paragraph) -> bool:
        # В 8 классе нет номеров глав (римских цифр). Heading 1 — часть
        # названия главы, поэтому не считаем его номером.
        return False


class Parser9KlassVseobschaya(BaseDocxParser):
    """9 класс — Всеобщая история.

    Структура глав (неоднородная внутри книги):
      - Главы I, II: «Г Л А В А    НАЗВАНИЕ» (название начинается на той же
        строке, что и «Г Л А В А»), продолжение названия — Normal и Heading 2.
      - Главы III, IV: «Г Л А В А» → номер (Heading 1) → название
        (Normal + Heading 2).
      - Параграфы: [Heading 3] § Название.

    Правило для этой книги:
      - Название главы может начинаться на той же строке, что и «Г Л А В А»
        (извлекается из строки «Г Л А В А    НАЗВАНИЕ»).
      - Название собирается из Normal + Heading 2 и завершается на первом
        параграфе (§).
    """

    def is_chapter_start(self, text: str) -> bool:
        # «Г Л А В А» или «Г Л А В А    НАЗВАНИЕ» (название на той же строке).
        m = re.match(r"^\s*Г\s*Л\s*А\s*В\s*А(?:\s+(.+))?\s*$", text)
        if m:
            self._pending_chapter_title = (m.group(1) or "").strip()
            return True
        return False

    def collect_chapter_title(self, paragraph, text, current_chapter,
                              collecting_chapter_name, collecting_chapter_title,
                              pending_paragraph_number) -> str:
        # Если название главы начиналось на той же строке, что и «Г Л А В А»,
        # добавляем его к названию главы.
        if getattr(self, "_pending_chapter_title", ""):
            current_chapter["title"] = self._pending_chapter_title
            self._pending_chapter_title = ""
        # Заголовок параграфа (§) — название главы закончилось.
        if self.is_paragraph_heading(paragraph) or (
            pending_paragraph_number and paragraph.style.name == "Heading 2"
        ):
            return "paragraph"
        # Подписи, главный вопрос, эпиграфы и «шум» — пропускаем.
        if self.is_caption_paragraph(text, paragraph_runs(paragraph)):
            return "skip"
        if "?" in text:
            return "skip"
        if text.startswith("«"):
            return "skip"
        runs = paragraph_runs(paragraph)
        if runs and any(r.get("bold") for r in runs) and any(r.get("italic") for r in runs):
            return "skip"
        # В этой книге название главы может быть разбито на несколько
        # параграфов (Normal + Heading 2). После названия идут подписи
        # к иллюстрациям и эпиграфы (Normal со смешанным регистром).
        # Поэтому Normal-параграф со смешанным регистром — это не часть
        # названия главы, завершаем сбор.
        if paragraph.style.name == "Normal" and not _is_uppercase_title(text):
            return "skip"
        # Добавляем текст к названию главы.
        if current_chapter["title"]:
            current_chapter["title"] += " " + text
        else:
            current_chapter["title"] = text
        # В этой книге название главы может быть разбито на несколько
        # параграфов (Normal + Heading 2), поэтому не завершаем сбор
        # на Heading 2 — продолжаем собирать продолжение.
        return "add"


class Parser10KlassRossii(BaseDocxParser):
    """10 класс — История России.

    Структура глав:
      - «ГЛАВА I» (Heading 1) → название (Heading 2) → продолжение
        названия (Normal, например «1914—1922 гг.»).
      - Параграфы: [Heading 3] § N Название.

    Правило для этой книги:
      - Название главы может продолжаться Normal-параграфом после Heading 2
        (например, «1914—1922 гг.»), поэтому не завершаем сбор на Heading 2.
    """

    def __init__(self, config):
        super().__init__(config)
        # Флаг: находимся ли мы внутри оглавления в конце книги.
        # Когда встречается «ОГЛАВЛЕНИЕ»/«СОДЕРЖАНИЕ», все последующие
        # параграфы (оглавление и служебная информация) пропускаются.
        self._in_toc = False

    def is_noise_line(self, text: str) -> bool:
        """Отфильтровывает оглавление в конце книги.

        Когда встречается «ОГЛАВЛЕНИЕ»/«СОДЕРЖАНИЕ», пропускаем все
        последующие параграфы (оглавление и служебную информацию).
        """
        if self._in_toc:
            return True
        if re.match(r"^(ОГЛАВЛЕНИЕ|СОДЕРЖАНИЕ)\s*$", text, re.IGNORECASE):
            self._in_toc = True
            return True
        return super().is_noise_line(text)

    def is_paragraph_heading(self, paragraph) -> bool:
        """Проверяет, является ли параграф заголовком параграфа (§).

        В этой книге настоящие параграфы — Heading 3 с «§ N Название».
        Служебные заголовки (Heading 3) «Введение», «Итоги главы»,
        «Вопросы и задания к главе», «ОГЛАВЛЕНИЕ»/«СОДЕРЖАНИЕ» не являются
        параграфами и должны быть отфильтрованы.
        """
        text = paragraph.text.strip()
        if paragraph.style.name == "Heading 3":
            # Настоящий параграф начинается с «§ N»
            if text.startswith("§"):
                return True
            # Служебные заголовки — не параграфы
            return False
        # В некоторых учебниках параграфы оформлены как Heading 2 с «§»
        if paragraph.style.name == "Heading 2" and text.startswith("§"):
            return True
        return False

    def collect_chapter_title(self, paragraph, text, current_chapter,
                              collecting_chapter_name, collecting_chapter_title,
                              pending_paragraph_number) -> str:
        # Заголовок параграфа (§) — название главы закончилось.
        if self.is_paragraph_heading(paragraph) or (
            pending_paragraph_number and paragraph.style.name == "Heading 2"
        ):
            return "paragraph"
        # Подписи, главный вопрос, эпиграфы и «шум» — пропускаем.
        if self.is_caption_paragraph(text, paragraph_runs(paragraph)):
            return "skip"
        if "?" in text:
            return "skip"
        if text.startswith("«"):
            return "skip"
        runs = paragraph_runs(paragraph)
        if runs and any(r.get("bold") for r in runs) and any(r.get("italic") for r in runs):
            return "skip"
        # Добавляем текст к названию главы.
        if current_chapter["title"]:
            current_chapter["title"] += " " + text
        else:
            current_chapter["title"] = text
        # Название главы заканчивается на Heading 2. Продолжение названия
        # с датами (например, «1914—1922 гг.») обрабатывается в parse_document
        # через lookahead. Подписи к иллюстрациям после Heading 2 не должны
        # попадать в название, поэтому завершаем сбор на Heading 2.
        if paragraph.style.name == "Heading 2":
            return "add_stop"
        return "add"


class Parser10KlassVseobschaya(BaseDocxParser):
    """10 класс — Всеобщая история.

    Структура глав:
      - «ГЛАВА    НАЗВАНИЕ» (Normal, название на той же строке) →
        продолжение названия (Normal) → номер главы (Heading 1, ПОСЛЕ
        названия) → текст главы (Body Text).
      - Параграфы: [Heading 3] § N Название.

    Правило для этой книги:
      - Название главы начинается на той же строке, что и «ГЛАВА»
        (извлекается из строки «ГЛАВА    НАЗВАНИЕ»).
      - Номер главы (Heading 1) идёт ПОСЛЕ названия.
      - Название собирается из Normal-параграфов и завершается на Body Text
        (текст главы) или на параграфе (§).
    """

    def is_paragraph_heading(self, paragraph) -> bool:
        """Проверяет, является ли параграф заголовком параграфа (§).

        В этой книге настоящие параграфы — Heading 2 с «§». Heading 3
        используется для колонтитула-разделителя «МИР РОССИЯ», который
        НЕ является началом параграфа (обрабатывается как sync_table).
        """
        text = paragraph.text.strip()
        # «иТоГи ГЛАВы» — это итоги главы, а не параграф
        if re.match(r"^иТоГи\s+ГЛАВы", text, re.IGNORECASE):
            return False
        # Heading 3 — колонтитул-разделитель «МИР РОССИЯ», не параграф
        if paragraph.style.name == "Heading 3":
            return False
        # Настоящие параграфы — Heading 2 с «§»
        if paragraph.style.name == "Heading 2" and text.startswith("§"):
            return True
        return False

    def is_noise_line(self, text: str) -> bool:
        """Отфильтровывает колонтитулы-разделители «МИР» и «РОССИЯ».

        В этой книге «МИР» и «РОССИЯ» (отдельные Heading 3) — это
        колонтитулы-разделители, которые не должны попадать в текст.
        """
        if re.match(r"^\s*МИР\s*$", text) or re.match(r"^\s*РОССИЯ\s*$", text):
            return True
        return super().is_noise_line(text)

    def is_chapter_start(self, text: str) -> bool:
        # «ГЛАВА    НАЗВАНИЕ» (название на той же строке).
        m = re.match(r"^\s*ГЛАВА\s+(.+)$", text)
        if m:
            self._pending_chapter_title = m.group(1).strip()
            return True
        return False

    def collect_chapter_title(self, paragraph, text, current_chapter,
                              collecting_chapter_name, collecting_chapter_title,
                              pending_paragraph_number) -> str:
        # Если название главы начиналось на той же строке, что и «ГЛАВА»,
        # добавляем его к названию главы.
        if getattr(self, "_pending_chapter_title", ""):
            current_chapter["title"] = self._pending_chapter_title
            self._pending_chapter_title = ""
        # Body Text — текст главы, название закончилось.
        if paragraph.style.name == "Body Text":
            return "skip"
        # Заголовок параграфа (§) — название главы закончилось.
        if self.is_paragraph_heading(paragraph) or (
            pending_paragraph_number and paragraph.style.name == "Heading 2"
        ):
            return "paragraph"
        # Подписи, главный вопрос, эпиграфы и «шум» — пропускаем.
        if self.is_caption_paragraph(text, paragraph_runs(paragraph)):
            return "skip"
        if "?" in text:
            return "skip"
        if text.startswith("«"):
            return "skip"
        runs = paragraph_runs(paragraph)
        if runs and any(r.get("bold") for r in runs) and any(r.get("italic") for r in runs):
            return "skip"
        # После номера главы (Heading 1) идут подписи к иллюстрациям
        # (Normal со смешанным регистром). Название главы набрано
        # прописными буквами, поэтому Normal со смешанным регистром —
        # это не часть названия, завершаем сбор. Исключение — диапазон
        # лет (например, «1939—1945 гг.»), который является продолжением
        # названия главы.
        if (
            paragraph.style.name == "Normal"
            and not _is_uppercase_title(text)
            and not _is_year_range(text)
        ):
            return "skip"
        # Добавляем текст к названию главы.
        if current_chapter["title"]:
            current_chapter["title"] += " " + text
        else:
            current_chapter["title"] = text
        return "add"


class ParserZa8Klass(BaseDocxParser):
    """8 класс — История России (задачник/рабочая тетрадь).

    Структура глав (неоднородная внутри книги):
      - «Г Л А В А» (Normal) → номер (Heading 1) → название (Heading 2 +
        Normal).
      - «Г Л А В А    НАЗВАНИЕ» (название на той же строке) → продолжение
        названия (Heading 2).
      - «Г Л А В А НАЗВАНИЕ» (Heading 2, маркер и название в одном параграфе).
      - Параграфы: [Heading 3] § Название.

    Правило для этой книги:
      - Название главы может начинаться на той же строке, что и «Г Л А В А».
      - Название собирается из Heading 2 + Normal и завершается на первом
        параграфе (§).
    """

    def __init__(self, config):
        super().__init__(config)
        # Флаг: находимся ли мы внутри служебного хвоста в конце книги
        # (ссылки на порталы, «ОГЛАВЛЕНИЕ», оглавление). Когда встречается
        # «Федеральный портал истории России» или «ОГЛАВЛЕНИЕ»/«СОДЕРЖАНИЕ»,
        # все последующие параграфы пропускаются.
        self._in_toc = False

    def is_noise_line(self, text: str) -> bool:
        """Отфильтровывает служебный хвост в конце книги.

        Когда встречается «Федеральный портал истории России» (начало списка
        ссылок на порталы) или «ОГЛАВЛЕНИЕ»/«СОДЕРЖАНИЕ», пропускаем все
        последующие параграфы (ссылки, оглавление и служебную информацию).
        """
        if self._in_toc:
            return True
        if re.match(r"^Федеральный портал истории России", text) or \
           re.match(r"^(ОГЛАВЛЕНИЕ|СОДЕРЖАНИЕ)\s*$", text, re.IGNORECASE):
            self._in_toc = True
            return True
        return super().is_noise_line(text)

    def is_chapter_start(self, text: str) -> bool:
        # «Г Л А В А» или «Г Л А В А    НАЗВАНИЕ» (название на той же строке).
        m = re.match(r"^\s*Г\s*Л\s*А\s*В\s*А(?:\s+(.+))?\s*$", text)
        if m:
            self._pending_chapter_title = (m.group(1) or "").strip()
            return True
        return False

    def collect_chapter_title(self, paragraph, text, current_chapter,
                              collecting_chapter_name, collecting_chapter_title,
                              pending_paragraph_number) -> str:
        # Если название главы начиналось на той же строке, что и «Г Л А В А»,
        # добавляем его к названию главы.
        if getattr(self, "_pending_chapter_title", ""):
            current_chapter["title"] = self._pending_chapter_title
            self._pending_chapter_title = ""
        # Заголовок параграфа (§) — название главы закончилось.
        if self.is_paragraph_heading(paragraph) or (
            pending_paragraph_number and paragraph.style.name == "Heading 2"
        ):
            return "paragraph"
        # Подписи, главный вопрос, эпиграфы и «шум» — пропускаем.
        if self.is_caption_paragraph(text, paragraph_runs(paragraph)):
            return "skip"
        if "?" in text:
            return "skip"
        if text.startswith("«"):
            return "skip"
        runs = paragraph_runs(paragraph)
        if runs and any(r.get("bold") for r in runs) and any(r.get("italic") for r in runs):
            return "skip"
        # Добавляем текст к названию главы.
        if current_chapter["title"]:
            current_chapter["title"] += " " + text
        else:
            current_chapter["title"] = text
        # Название главы может быть разбито на Heading 2 + Normal,
        # поэтому не завершаем сбор на Heading 2.
        return "add"


class ParserZa9Klass(BaseDocxParser):
    """9 класс — История России (задачник/рабочая тетрадь).

    Структура глав:
      - «Г Л А В А» (Normal) → номер (Heading 1 или Normal) → название
        (Heading 2 + Heading 3/Normal).
      - Параграфы: [Heading 4] § Название.
      - Продолжение названия главы может быть оформлено как Heading 3
        (без §) или Normal.

    Правило для этой книги:
      - Номер главы может быть в Normal (римская цифра).
      - Параграфы — Heading 4 с § (не Heading 3).
      - Название собирается из Heading 2 + Heading 3 (без §) + Normal
        и завершается на первом параграфе (§).
    """

    def __init__(self, config):
        super().__init__(config)
        # Флаг: находимся ли мы внутри служебного хвоста в конце книги
        # (ссылки на порталы, «ОГЛАВЛЕНИЕ», оглавление). Когда встречается
        # «Федеральный портал истории России» или «ОГЛАВЛЕНИЕ»/«СОДЕРЖАНИЕ»,
        # все последующие параграфы пропускаются.
        self._in_toc = False

    def is_noise_line(self, text: str) -> bool:
        """Отфильтровывает служебный хвост в конце книги.

        Когда встречается «Федеральный портал истории России» (начало списка
        ссылок на порталы) или «ОГЛАВЛЕНИЕ»/«СОДЕРЖАНИЕ», пропускаем все
        последующие параграфы (ссылки, оглавление и служебную информацию).
        """
        if self._in_toc:
            return True
        if re.match(r"^Федеральный портал истории России", text) or \
           re.match(r"^(ОГЛАВЛЕНИЕ|СОДЕРЖАНИЕ)\s*$", text, re.IGNORECASE):
            self._in_toc = True
            return True
        return super().is_noise_line(text)

    def is_chapter_number(self, paragraph) -> bool:
        # Номер главы — Heading 1 или Normal с римской цифрой.
        text = paragraph.text.strip()
        if paragraph.style.name == "Heading 1":
            return True
        if paragraph.style.name == "Normal" and re.match(r"^[IVX]+$", text):
            return True
        return False

    def is_paragraph_heading(self, paragraph) -> bool:
        # Параграфы в этой книге — Heading 4 с § (или Heading 3 с §).
        text = paragraph.text.strip()
        if re.match(r"^иТоГи\s+ГЛАВы", text, re.IGNORECASE):
            return False
        if paragraph.style.name == "Heading 4" and text.startswith("§"):
            return True
        if paragraph.style.name == "Heading 3" and text.startswith("§"):
            return True
        return False

    def is_chapter_summary(self, paragraph) -> bool:
        # Heading 4 с § — это параграф, а не итоги главы.
        text = paragraph.text.strip()
        if paragraph.style.name == "Heading 4" and text.startswith("§"):
            return False
        return super().is_chapter_summary(paragraph)

    def collect_chapter_title(self, paragraph, text, current_chapter,
                              collecting_chapter_name, collecting_chapter_title,
                              pending_paragraph_number) -> str:
        # Заголовок параграфа (§) — название главы закончилось.
        if self.is_paragraph_heading(paragraph) or (
            pending_paragraph_number and paragraph.style.name == "Heading 2"
        ):
            return "paragraph"
        # Подписи, главный вопрос, эпиграфы и «шум» — пропускаем.
        if self.is_caption_paragraph(text, paragraph_runs(paragraph)):
            return "skip"
        if "?" in text:
            return "skip"
        if text.startswith("«"):
            return "skip"
        runs = paragraph_runs(paragraph)
        if runs and any(r.get("bold") for r in runs) and any(r.get("italic") for r in runs):
            return "skip"
        # Добавляем текст к названию главы.
        if current_chapter["title"]:
            current_chapter["title"] += " " + text
        else:
            current_chapter["title"] = text
        # Название главы может быть разбито на Heading 2 + Heading 3/Normal,
        # поэтому не завершаем сбор на Heading 2.
        return "add"


class Parser11KlassVseobschaya(Parser10KlassVseobschaya):
    """11 класс — Всеобщая история.

    Структура глав:
      - «ГЛАВА    НАЗВАНИЕ» (Normal, название на той же строке) →
        продолжение названия (Normal) → текст главы.
      - Параграфы: в теле учебника НЕТ явных заголовков «§ N».
        Текст организован разделами [Normal] «N Название.» (например,
        «1 Появление биполярного мира.»). Каждый такой раздел считаем
        отдельным параграфом.

    Правило для этой книги:
      - Параграф — это раздел [Normal] «N Название.» (число + заглавная буква).
      - Название главы собирается из Normal-параграфов (смешанный регистр)
        до первого раздела-параграфа. Римская цифра номера главы (I, II, III…),
        встроенная в строку «ГЛАВА …», удаляется.
    """

    def is_chapter_start(self, text: str) -> bool:
        # «ГЛАВА    НАЗВАНИЕ» (название на той же строке).
        m = re.match(r"^\s*ГЛАВА\s+(.+)$", text)
        if m:
            self._pending_chapter_title = m.group(1).strip()
            return True
        return False

    def collect_chapter_title(self, paragraph, text, current_chapter,
                              collecting_chapter_name, collecting_chapter_title,
                              pending_paragraph_number) -> str:
        # Если название главы начиналось на той же строке, что и «ГЛАВА»,
        # добавляем его к названию главы.
        if getattr(self, "_pending_chapter_title", ""):
            current_chapter["title"] = self._pending_chapter_title
            self._pending_chapter_title = ""
        # Раздел [Normal] «N Название.» — это параграф, название главы закончилось.
        if self.is_paragraph_heading(paragraph):
            return "paragraph"
        # Body Text — текст главы, название закончилось.
        if paragraph.style.name == "Body Text":
            return "skip"
        # Подписи, вопросы — пропускаем.
        if self.is_caption_paragraph(text, paragraph_runs(paragraph)):
            return "skip"
        if "?" in text:
            return "skip"
        # Подпись к иллюстрации: короткий Normal-параграф (≤ 40 символов),
        # не содержащий римскую цифру века (XX, XXI) и не являющийся
        # диапазоном лет. Название главы закончилось.
        if (
            paragraph.style.name == "Normal"
            and len(text) <= 40
            and not re.search(r"\b[IVXLCDM]{2,}\b", text)
            and not _is_year_range(text)
        ):
            return "skip"
        # Собираем продолжение названия главы (Normal, смешанный регистр).
        if current_chapter["title"]:
            current_chapter["title"] += " " + text
        else:
            current_chapter["title"] = text
        return "add"

    def is_paragraph_heading(self, paragraph) -> bool:
        # Параграфы — разделы [Normal] «N Название.» (число + заглавная буква).
        text = paragraph.text.strip()
        if paragraph.style.name == "Normal" and re.match(r"^\d+\s+[А-ЯЁ]", text):
            return True
        return False


class Parser11KlassRossii(BaseDocxParser):
    """11 класс — История России.

    Структура:
      - Явных глав НЕТ. Параграфы идут напрямую: [Heading 1] «§ N Название».
      - Внутри параграфа: [Heading 2] РОССИЯ, [Heading 3] МИР,
        [Heading 4] спецблоки, [Heading 5] ПОДВЕДЁМ ИТОГИ, [Heading 6] вопросы.

    Правило для этой книги:
      - Создаём одну главу для всего учебника при первом параграфе.
      - Параграф — это [Heading 1] «§ N Название».
    """

    def is_chapter_start(self, text: str) -> bool:
        # Создаём одну главу при первом параграфе «§ N».
        if not getattr(self, "_chapter_created", False) and re.match(r"^\s*§\s*\d+", text):
            self._chapter_created = True
            return True
        return False

    def collect_chapter_title(self, paragraph, text, current_chapter,
                              collecting_chapter_name, collecting_chapter_title,
                              pending_paragraph_number) -> str:
        # Параграф «§ N» — название главы закончилось.
        if self.is_paragraph_heading(paragraph):
            return "paragraph"
        return "skip"

    def is_paragraph_heading(self, paragraph) -> bool:
        # Параграфы — [Heading 1] «§ N Название».
        text = paragraph.text.strip()
        if paragraph.style.name == "Heading 1" and text.startswith("§"):
            return True
        return False


# ---------------------------------------------------------------------------
# Реестр парсеров: выбор по имени файла.
# ---------------------------------------------------------------------------

# Ключ — подстрока имени файла (без учёта регистра), значение — класс парсера.
PARSER_REGISTRY: List[Dict[str, Any]] = [
    {
        "match": "5_klass",
        "parser": Parser5Klass,
        "config": "config_world_history.json",
    },
    {
        "match": "6_klass_vseobschaya",
        "parser": Parser6KlassVseobschaya,
        "config": "config_world_history.json",
    },
    {
        "match": "6_klass",
        "parser": Parser6KlassRossii,
        "config": "config_russia_history.json",
    },
    {
        "match": "7_klass_vseobschaya",
        "parser": Parser7KlassVseobschaya,
        "config": "config_world_history.json",
    },
    {
        "match": "7_klass",
        "parser": Parser7KlassRossii,
        "config": "config_russia_history.json",
    },
    {
        "match": "8_klass_vseobschaya",
        "parser": Parser8KlassVseobschaya,
        "config": "config_world_history.json",
    },
    {
        "match": "9_klass_vseobschaya",
        "parser": Parser9KlassVseobschaya,
        "config": "config_world_history.json",
    },
    {
        "match": "istoriya_rossii_10",
        "parser": Parser10KlassRossii,
        "config": "config_russia_history.json",
    },
    {
        "match": "vseobschaya_10",
        "parser": Parser10KlassVseobschaya,
        "config": "config_world_history.json",
    },
    {
        "match": "vseobschaya_11",
        "parser": Parser11KlassVseobschaya,
        "config": "config_world_history.json",
    },
    {
        "match": "istoriya_rossii_11",
        "parser": Parser11KlassRossii,
        "config": "config_russia_history.json",
    },
    {
        "match": "vseobschaya_11",
        "parser": Parser11KlassVseobschayaPdf,
        "config": "config_world_history.json",
        "is_pdf": True,
    },
    {
        "match": "istoriya_rossii_11",
        "parser": Parser11KlassRossiiPdf,
        "config": "config_russia_history.json",
        "is_pdf": True,
    },
    {
        "match": "za_8",
        "parser": ParserZa8Klass,
        "config": "config_russia_history.json",
    },
    {
        "match": "za_9",
        "parser": ParserZa9Klass,
        "config": "config_russia_history.json",
    },
]


def get_parser_for_file(filename: str) -> Optional[Dict[str, Any]]:
    """Возвращает запись реестра (класс парсера и конфиг) по имени файла.

    Ищет первое совпадение подстроки имени файла (без учёта регистра).
    Учитывает расширение файла: для .pdf выбирается PDF-парсер (is_pdf=True),
    для .docx — DOCX-парсер. Если совпадений нет — возвращает None.
    """
    name = filename.lower()
    is_pdf = name.endswith(".pdf")
    for entry in PARSER_REGISTRY:
        if entry["match"] in name and entry.get("is_pdf", False) == is_pdf:
            return entry
    return None
