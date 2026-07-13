"""L0 PDF Normalizer: гарантированное преобразование любого PDF в Universal Representation.

Принцип: извлечь ВСЕ примитивы (текст, векторы, растры) + пространственные отношения.
Никаких SKIP — любой вход → универсальный формат.
"""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import urllib.request

import fitz

from src.utils.config import OLLAMA_LOCAL_BASE

# LLM для разделения зон на mixed-страницах
VISION_MODEL = "qwen3-vl:30b"

ZONE_SEPARATION_PROMPT = """[РОЛЬ] Zone Separator
[ЗАДАЧА] Раздели страницу на смысловые зоны
[ПРАВИЛА]
- Для каждой зоны укажи: type (text/image/vector), bbox [x,y,w,h], label
- Если текст поверх картинки → зона "text-over-image"
- Если картинка с подписью → зона "image-with-caption", свяжи их
- Если фоновое изображение → зона "background", не смешивай с текстом
- Если мелкий логотип/декор → зона "decoration"
[ОГРАНИЧЕНИЕ] Не интерпретируй содержание зон. Только структура.

Формат вывода: JSON
{
  "zones": [
    {"type": "text", "bbox": [x, y, w, h], "label": "основной текст"},
    {"type": "image", "bbox": [x, y, w, h], "label": "диаграмма"},
    {"type": "text-over-image", "bbox": [x, y, w, h], "label": "подпись к диаграмме"}
  ],
  "page_classification": "mixed"
}"""

IMAGE_CONTENT_PROMPT = """[РОЛЬ] Image Content Extractor
[ЗАДАЧА] Извлеки текстовое содержание из изображения
[ПРАВИЛА]
- Если на изображении есть текст — извлеки его дословно
- Если это схема/диаграмма — опиши её структуру (узлы, связи, заголовки)
- Если это слайд презентации — перечисли заголовки и ключевые пункты
- Если это фотография — опиши, что на ней изображено
[ОГРАНИЧЕНИЕ] Не делай выводов о домене или назначении. Только извлечение содержания.

Формат вывода: JSON
{
  "has_text": true/false,
  "extracted_text": "дословный текст с изображения",
  "content_type": "slide/diagram/photo/document/other",
  "description": "краткое описание структуры изображения"
}"""


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
            })

    return {
        "text_blocks": text_blocks,
        "image_blocks": image_blocks,
        "vector_blocks": vector_blocks,
    }


def _call_image_content_extractor(page: fitz.Page, dpi: int = 150) -> dict:
    """Извлекает текст/содержание из изображения через qwen3-vl:30b."""
    pix = page.get_pixmap(dpi=dpi)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()

    data = json.dumps({
        "model": VISION_MODEL,
        "prompt": IMAGE_CONTENT_PROMPT,
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
            return json.loads(result_text[json_start:json_end])
    except (json.JSONDecodeError, KeyError):
        pass

    return {"has_text": False, "extracted_text": "", "content_type": "other", "description": ""}


def _call_tesseract_ocr(page: fitz.Page, dpi: int = 300) -> dict:
    """Извлекает текст из изображения через Tesseract OCR (детерминированно)."""
    pix = page.get_pixmap(dpi=dpi)
    
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        pix.save(tmp.name)
        tmp_path = tmp.name
    
    try:
        result = subprocess.run(
            ["tesseract", tmp_path, "stdout", "-l", "rus+eng", "--psm", "6"],
            capture_output=True, text=True, timeout=120,
        )
        text = result.stdout.strip()
    finally:
        import os
        os.unlink(tmp_path)
    
    has_text = len(text) > 10  # минимум 10 символов для признания текстом
    return {
        "has_text": has_text,
        "extracted_text": text,
        "content_type": "ocr_result",
        "description": "",
        "source": "tesseract",
    }


def _call_zone_separator(page: fitz.Page, dpi: int = 150) -> dict:
    """Вызывает LLM для разделения зон на mixed-странице."""
    pix = page.get_pixmap(dpi=dpi)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()

    data = json.dumps({
        "model": VISION_MODEL,
        "prompt": ZONE_SEPARATION_PROMPT,
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

    # Парсим JSON
    try:
        json_start = result_text.find("{")
        json_end = result_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(result_text[json_start:json_end])
    except (json.JSONDecodeError, KeyError):
        pass

    return {"zones": [], "page_classification": "mixed", "error": "parse_failed"}


def _classify_page_type(primitives: dict) -> str:
    """Классифицирует тип страницы по наличию примитивов.

    Векторы — амбивалентны: могут быть частью текстовой вёрстки или
    частью изображения. Поэтому их наличие не меняет text-only/image-only.
    """
    has_text = len(primitives["text_blocks"]) > 0
    has_images = len(primitives["image_blocks"]) > 0
    has_vectors = len(primitives["vector_blocks"]) > 0

    if not has_text and not has_images and not has_vectors:
        return "empty"
    if has_text and not has_images:
        return "text-only"  # текст (векторы — часть вёрстки)
    if not has_text and has_images:
        return "image-only"  # картинки (векторы — часть композиции)
    if not has_text and not has_images and has_vectors:
        return "vector-only"
    # Текст + картинки → mixed (нужен LLM для разделения зон)
    return "mixed"


def normalize(pdf_path: str, dpi: int = 150, separate_zones: bool = False) -> dict:
    """L0 Normalizer: преобразует PDF в Universal Representation.

    Args:
        pdf_path: путь к PDF-файлу
        dpi: разрешение для рендеринга
        separate_zones: вызывать LLM для разделения зон на mixed-страницах
                       (медленно — ~30s на страницу. Только когда нужен пространственный анализ)

    Returns:
        Universal Representation
    """
    doc = fitz.open(pdf_path)
    metadata = doc.metadata or {}
    pages = []

    for page_num in range(len(doc)):
        page = doc[page_num]

        # 1. Извлекаем ВСЕ примитивы
        primitives = _extract_page_primitives(page)

        # 2. Классифицируем тип
        page_type = _classify_page_type(primitives)

        # 3. Собираем элементы
        elements = []
        for text_block in primitives["text_blocks"]:
            elements.append({
                "type": "text",
                "bbox": text_block["bbox"],
                "content": text_block["text"],
            })
        for img_block in primitives["image_blocks"]:
            elements.append({
                "type": "image",
                "bbox": img_block["bbox"],
                "xref": img_block["xref"],
                "size": [img_block["width"], img_block["height"]],
            })
        for vec_block in primitives["vector_blocks"]:
            elements.append({
                "type": "vector",
                "bbox": vec_block["bbox"],
                "item_count": vec_block["item_count"],
            })

        # 4. Для mixed-страниц — LLM-разделение зон (опционально)
        zones = None
        if page_type == "mixed" and separate_zones:
            zones = _call_zone_separator(page, dpi=dpi)

        # 5. Для image-only страниц — извлечение текста из картинки
        image_content = None
        if page_type == "image-only":
            # Сначала пробуем vision model
            image_content = _call_image_content_extractor(page, dpi=dpi)
            
            # Если vision model не нашла текст — пробуем Tesseract
            if not image_content.get("has_text"):
                ocr_result = _call_tesseract_ocr(page)
                if ocr_result.get("has_text"):
                    image_content = ocr_result
            
            if image_content.get("has_text") and image_content.get("extracted_text"):
                elements.append({
                    "type": "ocr_text",
                    "bbox": [0, 0, int(page.rect.width), int(page.rect.height)],
                    "content": image_content["extracted_text"],
                    "source": image_content.get("source", "vision_model"),
                })
                page_type = "image-with-text"

        pages.append({
            "page_id": page_num + 1,
            "width": int(page.rect.width),
            "height": int(page.rect.height),
            "page_type": page_type,
            "elements": elements,
            "zones": zones,
            "image_content": image_content,
            "primitives_raw": primitives,
        })

    doc.close()

    # Статистика
    type_counts = {}
    for p in pages:
        t = p["page_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "pages": pages,
        "metadata": {
            "author": metadata.get("author", ""),
            "creator": metadata.get("creator", ""),
            "producer": metadata.get("producer", ""),
            "creation_date": metadata.get("creationDate", ""),
            "title": metadata.get("title", ""),
            "format": metadata.get("format", ""),
            "page_count": len(pages),
        },
        "stats": {
            "total_pages": len(pages),
            "page_types": type_counts,
        },
    }