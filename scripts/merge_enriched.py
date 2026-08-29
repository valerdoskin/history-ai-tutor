#!/usr/bin/env python3
"""Подмешивает обогащённые метаданные из knowledge/enriched.json в knowledge/chunks.json.

Ключ параграфа в enriched.json:  book_id::chapter_number::paragraph_title
Ключ чанка в chunks.json:       book_id::chapter_number::paragraph_title::chunk_index
"""
import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("merge_enriched")


def load_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    parser = argparse.ArgumentParser(description="Подмешивание enriched.json в chunks.json")
    parser.add_argument("--chunks", default="knowledge/chunks.json")
    parser.add_argument("--enriched", default="knowledge/enriched.json")
    parser.add_argument("--output", default="knowledge/chunks.json")
    args = parser.parse_args()

    chunks = load_json(Path(args.chunks))
    enriched = load_json(Path(args.enriched))

    logger.info("Чанков: %d, обогащённых параграфов: %d", len(chunks), len(enriched))

    matched = 0
    unmatched_chunks = 0
    for chunk in chunks:
        # Для параграфов без заголовка (PDF 11 класса) используем page_start,
        # чтобы ключ совпадал с ключом в enriched.json.
        para_title = chunk.get("paragraph_title", "")
        if para_title:
            para_key = f"{chunk['book_id']}::{chunk['chapter_number']}::{para_title}"
        else:
            para_key = f"{chunk['book_id']}::{chunk['chapter_number']}::__p{chunk.get('page_start', '')}"
        meta = enriched.get(para_key, {}).get("metadata", {})
        chunk["metadata"] = meta
        if meta:
            matched += 1
        else:
            unmatched_chunks += 1

    with_meta = sum(1 for c in chunks if c["metadata"])
    logger.info("Чанков с метаданными: %d / %d", with_meta, len(chunks))
    logger.info("Чанков без метаданных: %d", unmatched_chunks)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(chunks, fh, ensure_ascii=False, indent=2)
    logger.info("Сохранено: %s", out)


if __name__ == "__main__":
    main()
