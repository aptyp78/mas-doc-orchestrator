"""ОРП 5: Visual Extractor.

Извлекает визуальные примитивы из страницы через PyMuPDF (детерминированно, без LLM).
Классифицирует страницу и drawings.
"""

from __future__ import annotations

import fitz

ROLE = (
    "[РОЛЬ] Visual Extractor\n"
    "[ОБЪЕКТ] Растровое изображение страницы\n"
    "[ПРАВИЛА] Классификация: text-only | image-only | mixed. "
    "Drawings: decorative | structural | table.\n"
    "[ОГРАНИЧЕНИЕ] Не интерпретируй содержание. Только структура и классификация."
)

PROMPT = ROLE  # Эта роль не использует LLM — промпт чисто декларативный


def run(
    pdf_path: str,
    page_number: int = 0,
    extract_primitives: bool = True,
) -> dict:
    """Извлекает визуальные примитивы и классифицирует страницу.

    Args:
        pdf_path: путь к PDF-файлу
        page_number: номер страницы (0-indexed)
        extract_primitives: извлекать ли примитивы (text, image, vector)

    Returns:
        dict с page_classification, primitives, drawings_classification
    """
    doc = fitz.open(pdf_path)
    
    if page_number >= len(doc):
        doc.close()
        return {
            "page_classification": "unknown",
            "primitives": {},
            "drawings_classification": [],
            "error": f"Page {page_number} out of range (total: {len(doc)})",
        }
    
    page = doc[page_number]
    
    # Извлекаем примитивы
    primitives = {}
    if extract_primitives:
        primitives = _extract_page_primitives(page)
    
    # Классифицируем страницу
    page_classification = _classify_page(primitives)
    
    # Классифицируем drawings
    drawings_classification = _classify_drawings(primitives.get("vector_blocks", []))
    
    total_pages = len(doc)
    doc.close()
    
    return {
        "page_classification": page_classification,
        "primitives": primitives,
        "drawings_classification": drawings_classification,
        "page_number": page_number,
        "total_pages": total_pages,
    }


def _extract_page_primitives(page: fitz.Page) -> dict:
    """Извлекает все примитивы со страницы через PyMuPDF (детерминированно)."""
    # Текстовые блоки
    text_blocks = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] == 0:  # text block
            text_content = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text_content += span.get("text", "")
            text_blocks.append({
                "type": "text",
                "bbox": list(block["bbox"]),
                "text": text_content,
                "block_no": block.get("number", 0),
            })

    # Изображения
    image_blocks = []
    for img_info in page.get_images(full=True):
        try:
            img_bbox = page.get_image_bbox(img_info)
            if img_bbox:
                image_blocks.append({
                    "type": "image",
                    "bbox": list(img_bbox),
                    "xref": img_info[0],
                    "width": img_info[2],
                    "height": img_info[3],
                })
        except Exception:
            pass

    # Векторные пути (drawings)
    vector_blocks = []
    for drawing in page.get_drawings():
        items = drawing.get("items", [])
        if items:
            vector_blocks.append({
                "type": "vector",
                "bbox": list(drawing["rect"]),
                "item_count": len(items),
                "color": drawing.get("color"),
                "fill": drawing.get("fill"),
            })

    return {
        "text_blocks": text_blocks,
        "image_blocks": image_blocks,
        "vector_blocks": vector_blocks,
    }


def _classify_page(primitives: dict) -> str:
    """Классифицирует страницу: text-only | image-only | mixed."""
    text_blocks = primitives.get("text_blocks", [])
    image_blocks = primitives.get("image_blocks", [])
    vector_blocks = primitives.get("vector_blocks", [])
    
    has_text = len(text_blocks) > 0
    has_images = len(image_blocks) > 0
    has_vectors = len(vector_blocks) > 0
    
    if has_text and not has_images and not has_vectors:
        return "text-only"
    elif has_images and not has_text:
        return "image-only"
    elif has_text and (has_images or has_vectors):
        return "mixed"
    elif has_vectors and not has_text:
        return "vector-only"
    else:
        return "unknown"


def _classify_drawings(vector_blocks: list[dict]) -> list[dict]:
    """Классифицирует drawings: decorative | structural | table.

    Эвристики:
    - decorative: мелкие элементы, без текста, одиночные
    - structural: линии, разделяющие страницу, рамки
    - table: сетка линий, образующих ячейки
    """
    classifications = []
    
    for i, drawing in enumerate(vector_blocks):
        bbox = drawing.get("bbox", [0, 0, 0, 0])
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        item_count = drawing.get("item_count", 0)
        
        # Эвристика для table: много элементов, образующих сетку
        if item_count > 10:
            classification = "table"
        # Эвристика для structural: линии во всю ширину/высоту
        elif width > 400 or height > 600:
            classification = "structural"
        # Остальное — decorative
        else:
            classification = "decorative"
        
        classifications.append({
            "drawing_index": i,
            "classification": classification,
            "bbox": bbox,
            "item_count": item_count,
            "confidence": 0.7,  # Эвристика, не LLM
        })
    
    return classifications
