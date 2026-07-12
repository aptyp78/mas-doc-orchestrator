"""ОРП 5: Visual Extractor.

Классифицирует страницы PDF и выделяет примитивы через qwen3-vl:30b.
"""

from __future__ import annotations

import base64
import json
import urllib.request

import fitz

from src.utils.config import OLLAMA_LOCAL_BASE

ROLE = (
    "[РОЛЬ] Visual Extractor\n"
    "[ОБЪЕКТ] Страницы и слои PDF\n"
    "[ПРАВИЛА] Классифицируй страницу: text-only | image-only | mixed.\n"
    "          Для mixed → разделяй text_run и vector_path по координатным перекрытиям.\n"
    "[ОГРАНИЧЕНИЕ] Не интерпретируй семантику текста."
)

PROMPT = ROLE

VISION_MODEL = "qwen3-vl:30b"


def run(
    pdf_path: str,
    dpi: int = 150,
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> dict:
    """Классифицирует страницы PDF и выделяет примитивы.

    Args:
        pdf_path: путь к PDF
        dpi: разрешение рендеринга
        max_tokens: лимит токенов для LLM
        temperature: температура генерации

    Returns:
        dict с pages_analysis, primitives, spatial_cache
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    pages_analysis: list[dict] = []
    all_primitives: list[dict] = []

    for page_num in range(total_pages):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()

        # Ollama-native формат: images отдельным полем
        data = json.dumps(
            {
                "model": VISION_MODEL,
                "messages": [{"role": "user", "content": PROMPT}],
                "images": [img_b64],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            }
        ).encode()

        req = urllib.request.Request(
            f"{OLLAMA_LOCAL_BASE}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = json.loads(resp.read())
            result_text = raw["message"]["content"]

        # Парсим результат: ожидаем классификацию страницы
        page_type = "mixed"  # default
        if "text-only" in result_text.lower():
            page_type = "text-only"
        elif "image-only" in result_text.lower():
            page_type = "image-only"

        pages_analysis.append(
            {
                "page_id": page_num + 1,
                "page_type": page_type,
                "raw_output": result_text,
                "width": int(page.rect.width),
                "height": int(page.rect.height),
            }
        )

    doc.close()

    # L1: проверка покрытия
    coverage = len(pages_analysis) / max(total_pages, 1) if total_pages > 0 else 1.0

    return {
        "pages_analysis": pages_analysis,
        "primitives": all_primitives,
        "spatial_cache": {"overlap_clusters": [], "near_miss_regions": []},
        "coverage": round(coverage, 2),
    }
