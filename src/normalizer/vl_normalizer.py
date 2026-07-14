"""VL Normalizer: альтернативный L0-нормализатор на Qwen3-VL.

Экспериментальная ветка — сравнивается с pdf_normalizer.py (PyMuPDF).
Использует Qwen3-VL для извлечения layout + текста из растра страницы.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.request

import fitz

from src.utils.config import OLLAMA_LOCAL_BASE

VISION_MODEL = "qwen3-vl:30b"

VL_PARSE_PROMPT = """[РОЛЬ] Позиция экстрактора структуры документа
[ПРЕДМЕТ] Растровое изображение страницы PDF
[ПРАВИЛА]
1. Извлеки ВЕСЬ текст со страницы с координатами bounding box
2. Определи тип каждого блока: text / image / table / header / footer
3. Для таблиц — извлеки структуру (строки × столбцы)
4. Выдай результат в JSON с массивом blocks
[ОГРАНИЧЕНИЕ]
- Не интерпретируй содержание. Только структура и текст.
- Координаты в пикселях от левого верхнего угла.
- Выводи строго JSON.

## СХЕМА JSON
{
  "blocks": [
    {
      "type": "text|image|table|header|footer",
      "bbox": [x, y, w, h],
      "text": "string",
      "confidence": "HIGH|MEDIUM|LOW"
    }
  ],
  "page_classification": "text-only|image-only|mixed",
  "language": "string"
}"""


def normalize_vl(pdf_path: str, dpi: int = 150) -> dict:
    """VL-нормализатор: извлекает структуру через Qwen3-VL.

    Args:
        pdf_path: путь к PDF
        dpi: разрешение рендеринга

    Returns:
        Universal Representation (совместим с pdf_normalizer)
    """
    doc = fitz.open(pdf_path)
    pages = []
    timings = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()

        t0 = time.time()
        data = json.dumps({
            "model": VISION_MODEL,
            "prompt": VL_PARSE_PROMPT,
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

        elapsed_s = time.time() - t0
        timings.append(elapsed_s)

        # Парсим JSON
        try:
            json_start = result_text.find("{")
            json_end = result_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(result_text[json_start:json_end])
            else:
                parsed = {"blocks": [], "page_classification": "unknown", "language": "unknown"}
        except (json.JSONDecodeError, KeyError):
            parsed = {"blocks": [], "page_classification": "unknown", "language": "unknown"}

        # Конвертируем в Universal Representation
        elements = []
        for block in parsed.get("blocks", []):
            elements.append({
                "type": block.get("type", "text"),
                "bbox": block.get("bbox", [0, 0, 0, 0]),
                "content": block.get("text", ""),
                "confidence": block.get("confidence", "MEDIUM"),
            })

        pages.append({
            "page_id": page_num + 1,
            "width": int(page.rect.width),
            "height": int(page.rect.height),
            "page_type": parsed.get("page_classification", "mixed"),
            "elements": elements,
            "vl_raw": parsed,
        })

    doc.close()

    type_counts = {}
    for p in pages:
        t = p["page_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "pages": pages,
        "metadata": {"source": "vl_normalizer", "model": VISION_MODEL},
        "stats": {
            "total_pages": len(pages),
            "page_types": type_counts,
            "avg_time_per_page_s": round(sum(timings) / max(len(timings), 1), 1),
            "total_time_s": round(sum(timings), 1),
        },
    }


def compare_normalizers(pdf_path: str) -> dict:
    """Сравнивает PyMuPDF и VL-нормализаторы на одном документе.

    Returns:
        dict с результатами сравнения
    """
    from src.normalizer.pdf_normalizer import normalize as pymupdf_normalize

    t0 = time.time()
    pymupdf_result = pymupdf_normalize(pdf_path)
    pymupdf_time = time.time() - t0

    t0 = time.time()
    vl_result = normalize_vl(pdf_path)
    vl_time = time.time() - t0

    pymupdf_pages = pymupdf_result["pages"]
    vl_pages = vl_result["pages"]

    comparison = {
        "document": pdf_path,
        "pymupdf": {
            "time_s": round(pymupdf_time, 1),
            "pages": len(pymupdf_pages),
            "elements_total": sum(len(p.get("elements", [])) for p in pymupdf_pages),
            "text_chars": sum(
                len(e.get("content", "")) for p in pymupdf_pages
                for e in p.get("elements", [])
                if e.get("type") in ("text", "ocr_text")
            ),
        },
        "vl": {
            "time_s": round(vl_time, 1),
            "pages": len(vl_pages),
            "elements_total": sum(len(p.get("elements", [])) for p in vl_pages),
            "text_chars": sum(
                len(e.get("content", "")) for p in vl_pages
                for e in p.get("elements", [])
            ),
        },
        "winner": "pymupdf" if pymupdf_time < vl_time else "vl",
        "time_ratio": round(vl_time / max(pymupdf_time, 0.1), 1),
    }

    return comparison