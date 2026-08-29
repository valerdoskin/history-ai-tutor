"""Предвычисляет embeddings всех уникальных exam_questions и сохраняет на диск.

Результат:
  knowledge/question_embeddings.npy  — матрица embeddings (N x 1024)
  knowledge/question_embeddings.json — список вопросов с метаданными
                                       (question, answer, class, paragraph)
"""

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import embedding_service
from services.placement_service import get_class_from_source

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")
CHUNKS = os.path.join(BASE, "chunks.json")
OUT_NPY = os.path.join(BASE, "question_embeddings.npy")
OUT_JSON = os.path.join(BASE, "question_embeddings.json")


def main():
    chunks = json.load(open(CHUNKS, encoding="utf-8"))
    seen = {}
    for ch in chunks:
        cls = get_class_from_source(ch.get("source_file", ""))
        meta = ch.get("metadata") or {}
        if isinstance(meta, list):
            meta = {"dates": meta}
        paragraph = str(ch.get("paragraph_title", "")).strip()
        for q in meta.get("exam_questions", []):
            question = str(q.get("question", "")).strip()
            answer = str(q.get("answer", "")).strip()
            if not question or not answer:
                continue
            if question in seen:
                continue
            seen[question] = {
                "question": question,
                "answer": answer,
                "class": cls,
                "paragraph": paragraph,
            }

    questions = list(seen.values())
    texts = [q["question"] for q in questions]
    print(f"Уникальных вопросов: {len(texts)}")
    vecs = embedding_service.embed_texts(texts)
    np.save(OUT_NPY, np.array(vecs))
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    print(f"Сохранено: {OUT_NPY} ({vecs.shape}), {OUT_JSON}")


if __name__ == "__main__":
    main()
