"""Уровень 1: Семиотический классификатор знаковых форм.

Определяет, в какой знаковой форме зафиксирована мысль на странице:
- narrative (текст)
- venn (диаграмма множеств)
- table (таблица)
- diagram (блок-схема, процесс)
- list (список)
- mixed (несколько форм)

Использует qwen3-vl:30b для классификации страницы.

Также определяет класс по модальности (L0) для динамического порога confidence:
- text_only: только текстовые примитивы
- mixed_text_vector: текст + векторная графика
- mixed_text_image: текст + растровые изображения
- complex_diagram: сложные диаграммы (Venn, графики)
"""

from __future__ import annotations

import base64
import json
import urllib.request

import fitz

from src.utils.config import OLLAMA_LOCAL_BASE
from src.utils.prompt_loader import load_prompt

VISION_MODEL = "qwen3-vl:30b"

# Загружаем промпт из файла
SEMIOTIC_PROMPT = load_prompt("semiotic/classifier")


def classify_modality(page: fitz.Page) -> dict:
    """Определяет класс документа по модальности (L0).
    
    Анализирует примитивы страницы и определяет класс по модальности
    для динамического порога confidence в DoubtGate.
    
    Returns:
        dict с modality_class и статистикой примитивов
    """
    # Извлекаем примитивы страницы
    text_blocks = []
    vector_blocks = []
    image_blocks = []
    
    # Текстовые блоки
    for block in page.get_text("dict")["blocks"]:
        if block["type"] == 0:  # text block
            text_blocks.append(block)
    
    # Векторные пути (drawings)
    for drawing in page.get_drawings():
        items = drawing.get("items", [])
        if items:
            vector_blocks.append(drawing)
    
    # Изображения
    for img_info in page.get_images(full=True):
        try:
            img_bbox = page.get_image_bbox(img_info)
            if img_bbox:
                image_blocks.append({
                    "bbox": list(img_bbox),
                    "xref": img_info[0],
                })
        except Exception:
            pass
    
    # Определяем класс по модальности
    has_text = len(text_blocks) > 0
    has_vectors = len(vector_blocks) > 0
    has_images = len(image_blocks) > 0
    
    # Эвристика для complex_diagram: много векторных элементов или изображений
    is_complex_diagram = (
        len(vector_blocks) > 10 or  # Много векторных элементов
        len(image_blocks) > 3 or    # Много изображений
        any(len(d.get("items", [])) > 20 for d in vector_blocks)  # Сложные drawings
    )
    
    if is_complex_diagram:
        modality_class = "complex_diagram"
    elif has_text and has_images:
        modality_class = "mixed_text_image"
    elif has_text and has_vectors:
        modality_class = "mixed_text_vector"
    elif has_text:
        modality_class = "text_only"
    else:
        modality_class = "text_only"  # Дефолт
    
    return {
        "modality_class": modality_class,
        "text_blocks": len(text_blocks),
        "vector_blocks": len(vector_blocks),
        "image_blocks": len(image_blocks),
        "is_complex_diagram": is_complex_diagram,
    }


def classify_page(page: fitz.Page, dpi: int = 150) -> dict:
    """Классифицирует знаковую форму страницы и определяет класс по модальности."""
    # L0: Класс по модальности (без LLM, быстро)
    modality = classify_modality(page)
    
    # L1: Знаковая форма СМД (через VL-модель, медленно)
    pix = page.get_pixmap(dpi=dpi)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()

    data = json.dumps({
        "model": VISION_MODEL,
        "prompt": SEMIOTIC_PROMPT,
        "images": [img_b64],
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = json.loads(resp.read())
        result_text = raw["response"]

    try:
        json_start = result_text.find("{")
        json_end = result_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            semiotic = json.loads(result_text[json_start:json_end])
            # Добавляем modality_class в результат
            semiotic["modality_class"] = modality["modality_class"]
            semiotic["modality_stats"] = {
                "text_blocks": modality["text_blocks"],
                "vector_blocks": modality["vector_blocks"],
                "image_blocks": modality["image_blocks"],
            }
            return semiotic
    except (json.JSONDecodeError, KeyError):
        pass

    return {
        "primary_form": "discursive",
        "secondary_forms": [],
        "confidence": "LOW",
        "rationale": "parse_failed",
        "modality_class": modality["modality_class"],
        "modality_stats": {
            "text_blocks": modality["text_blocks"],
            "vector_blocks": modality["vector_blocks"],
            "image_blocks": modality["image_blocks"],
        },
    }


def classify_document(pdf_path: str, dpi: int = 150) -> dict:
    """Классифицирует все страницы документа по знаковым формам."""
    doc = fitz.open(pdf_path)
    pages = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        classification = classify_page(page, dpi=dpi)
        pages.append({
            "page_id": page_num + 1,
            "width": int(page.rect.width),
            "height": int(page.rect.height),
            "primary_form": classification.get("primary_form", "narrative"),
            "secondary_forms": classification.get("secondary_forms", []),
            "confidence": classification.get("confidence", "LOW"),
            "rationale": classification.get("rationale", ""),
        })

    doc.close()

    # Статистика форм
    form_counts = {}
    for p in pages:
        f = p["primary_form"]
        form_counts[f] = form_counts.get(f, 0) + 1

    return {
        "pages": pages,
        "stats": {
            "total_pages": len(pages),
            "form_distribution": form_counts,
        },
    }