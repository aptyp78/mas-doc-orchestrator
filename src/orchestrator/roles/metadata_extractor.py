"""ОРП 1: Metadata & Provenance Extractor.

Извлекает атрибуты PDF без LLM — через PyMuPDF.
"""

from __future__ import annotations

import hashlib
import os

import fitz

ROLE = (
    "[РОЛЬ] Metadata & Provenance Extractor\n"
    "[ОБЪЕКТ] PDF-документ\n"
    "[ПРАВИЛА] Извлекай ≥8 атрибутов. Отсутствующие → MISSING. Конфиденциальные → MASKED.\n"
    "[ОГРАНИЧЕНИЕ] Не интерпретируй содержимое страниц."
)

PROMPT = ROLE  # Эта роль не использует LLM — промпт чисто декларативный

REQUIRED_ATTRS = [
    "Author",
    "Creator",
    "Producer",
    "CreationDate",
    "ModifyDate",
    "PageCount",
    "Format",
    "FileSize",
]


def run(pdf_path: str, document_id: str | None = None) -> dict:
    """Извлекает метаданные PDF.

    Args:
        pdf_path: путь к PDF-файлу
        document_id: идентификатор документа (если None — генерируется)

    Returns:
        dict с metadata_map, missing_fields, extraction_confidence, provenance_hash
    """
    doc = fitz.open(pdf_path)
    metadata = doc.metadata or {}
    page_count = len(doc)

    # Размер файла
    file_size = os.path.getsize(pdf_path)

    # Собираем атрибуты
    metadata_map: dict[str, str] = {}
    missing_fields: list[str] = []

    attr_sources = {
        "Author": metadata.get("author", ""),
        "Creator": metadata.get("creator", ""),
        "Producer": metadata.get("producer", ""),
        "CreationDate": metadata.get("creationDate", ""),
        "ModifyDate": metadata.get("modDate", ""),
        "PageCount": str(page_count),
        "Format": metadata.get("format", "PDF"),
        "FileSize": str(file_size),
    }

    for attr in REQUIRED_ATTRS:
        value = attr_sources.get(attr, "")
        if value:
            metadata_map[attr] = value
        else:
            metadata_map[attr] = "MISSING"
            missing_fields.append(attr)

    # Добавляем дополнительные атрибуты из метаданных
    for key, value in metadata.items():
        if key not in metadata_map and value:
            metadata_map[key] = str(value)

    # Provenance hash
    with open(pdf_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    doc_id = (
        document_id
        or hashlib.md5(
            f"{metadata_map.get('Author', '')}{metadata_map.get('CreationDate', '')}{file_size}".encode()
        ).hexdigest()[:8]
    )

    doc.close()

    # L1: проверка полноты
    extraction_confidence = 1.0 - (len(missing_fields) / len(REQUIRED_ATTRS))

    return {
        "metadata_map": metadata_map,
        "missing_fields": missing_fields,
        "extraction_confidence": round(extraction_confidence, 2),
        "provenance_hash": file_hash,
        "document_id": doc_id,
    }
