#!/usr/bin/env python3
"""
Этап 3: Разбиение на чанки для RAG.

Объединяет текст параграфов из output/*.json с метаданными из knowledge/enriched.json
и разбивает на чанки для векторного поиска.

Выход: knowledge/chunks.json
Формат чанка:
{
  "id": "world_history::I::§ Древнейшие люди::0",
  "book_id": "world_history",
  "book_line": "Всеобщая история",
  "chapter_title": "ПЕРВОБЫТНОЕ ОБЩЕСТВО",
  "chapter_number": "I",
  "paragraph_title": "§ Древнейшие люди",
  "paragraph_number": "",
  "page_start": 5,
  "page_end": 8,
  "main_question": "...",
  "chunk_index": 0,
  "chunk_total": 3,
  "text": "...",          # текст чанка
  "metadata": { ... }     # обогащённые метаданные (если есть)
}
"""

import argparse
import glob
import json
import logging
import os
import re

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Настройки чанкинга
DEFAULT_CHUNK_SIZE = 1200      # символов на чанк
DEFAULT_OVERLAP = 150          # перекрытие между чанками


def load_output_files(output_dir):
    """Загружает все output/*.json и возвращает список параграфов с текстом."""
    paragraphs = []
    for f in sorted(glob.glob(os.path.join(output_dir, "*.json"))):
        if os.path.basename(f) == "report.json":
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            logger.error(f"Не удалось прочитать {f}: {e}")
            continue

        book_id = data.get("book_id", os.path.basename(f).replace(".json", ""))
        book_line = data.get("book_line", "")
        source_file = data.get("source_file", os.path.basename(f))

        for chapter in data.get("data", []):
            chapter_number = chapter.get("number", "")
            chapter_title = chapter.get("title", "")
            for para in chapter.get("paragraphs", []):
                paragraphs.append({
                    "book_id": book_id,
                    "book_line": book_line,
                    "source_file": source_file,
                    "chapter_number": chapter_number,
                    "chapter_title": chapter_title,
                    "paragraph_title": para.get("title", ""),
                    "paragraph_number": para.get("number", ""),
                    "page_start": para.get("page_start", ""),
                    "page_end": para.get("page_end", ""),
                    "main_question": para.get("main_question", ""),
                    "content": para.get("content", []),
                })
    return paragraphs


def load_enriched(enriched_path):
    """Загружает knowledge/enriched.json и возвращает dict по para_key."""
    if not os.path.exists(enriched_path):
        logger.warning(f"Файл {enriched_path} не найден. Метаданные будут пустыми.")
        return {}
    with open(enriched_path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data


def para_key(book_id, chapter_number, title):
    return f"{book_id}::{chapter_number}::{title}"


def content_to_text(content):
    """Преобразует content (список строк/блоков) в единый текст."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                # блоки могут быть dict (например, {"type": "...", "text": "..."})
                if "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(parts)
    return str(content)


def split_text(text, chunk_size, overlap):
    """Разбивает текст на чанки с перекрытием."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # Стараемся резать по границе предложения/абзаца
        if end < len(text):
            # Ищем последний перенос строки или точку в окне
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("! "), window.rfind("? "))
            if cut > chunk_size * 0.5:
                end = start + cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_chunks(paragraphs, enriched, chunk_size, overlap):
    """Строит чанки из параграфов и метаданных."""
    chunks = []
    total_paras = len(paragraphs)
    for i, para in enumerate(paragraphs):
        key = para_key(para["book_id"], para["chapter_number"], para["paragraph_title"])
        meta = enriched.get(key, {}).get("metadata", {}) if key in enriched else {}

        text = content_to_text(para["content"])
        if not text.strip():
            logger.warning(f"[{i+1}/{total_paras}] Пустой текст: {key}")
            continue

        # Добавляем main_question в начало текста как контекст
        full_text = text
        if para["main_question"]:
            full_text = f"Главный вопрос параграфа: {para['main_question']}\n\n{text}"

        parts = split_text(full_text, chunk_size, overlap)
        for ci, part in enumerate(parts):
            chunks.append({
                "id": f"{key}::{ci}",
                "book_id": para["book_id"],
                "book_line": para["book_line"],
                "source_file": para["source_file"],
                "chapter_title": para["chapter_title"],
                "chapter_number": para["chapter_number"],
                "paragraph_title": para["paragraph_title"],
                "paragraph_number": para["paragraph_number"],
                "page_start": para["page_start"],
                "page_end": para["page_end"],
                "main_question": para["main_question"],
                "chunk_index": ci,
                "chunk_total": len(parts),
                "text": part,
                "metadata": meta,
            })
        if (i + 1) % 50 == 0:
            logger.info(f"[{i+1}/{total_paras}] Обработано параграфов, чанков: {len(chunks)}")
    return chunks


def main():
    parser = argparse.ArgumentParser(description="Разбиение на чанки для RAG")
    parser.add_argument("--output-dir", default="output", help="Папка с output/*.json")
    parser.add_argument("--enriched", default="knowledge/enriched.json", help="Файл enriched.json")
    parser.add_argument("--out", default="knowledge/chunks.json", help="Выходной файл")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="Размер чанка в символах")
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP, help="Перекрытие чанков")
    args = parser.parse_args()

    logger.info("Загрузка параграфов из output/...")
    paragraphs = load_output_files(args.output_dir)
    logger.info(f"Загружено параграфов: {len(paragraphs)}")

    logger.info(f"Загрузка метаданных из {args.enriched}...")
    enriched = load_enriched(args.enriched)
    logger.info(f"Загружено записей с метаданными: {len(enriched)}")

    logger.info(f"Разбиение на чанки (size={args.chunk_size}, overlap={args.overlap})...")
    chunks = build_chunks(paragraphs, enriched, args.chunk_size, args.overlap)
    logger.info(f"Всего чанков: {len(chunks)}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(chunks, fh, ensure_ascii=False, indent=2)
    logger.info(f"Сохранено: {args.out}")

    # Статистика
    with_meta = sum(1 for c in chunks if c["metadata"])
    logger.info(f"Чанков с метаданными: {with_meta} / {len(chunks)}")


if __name__ == "__main__":
    main()
