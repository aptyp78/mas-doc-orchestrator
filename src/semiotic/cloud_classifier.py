"""Уровень 1: Семиотический классификатор (Cloud — DashScope).

Использует qwen3-vl-plus через DashScope ModelStudio для быстрой классификации.
~3-5 сек/страницу против 50 сек/страницу у локальной Ollama.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz

from src.utils.config import DASHSCOPE_KEY, DASHSCOPE_BASE
from src.utils.prompt_loader import load_prompt

VISION_MODEL = "qwen3-vl-plus"
MAX_WORKERS = 6

SEMIOTIC_PROMPT = load_prompt("semiotic/cloud_classifier")


def _classify_one(page_num: int, img_b64: str, api_key: str) -> dict:
    """Классифицирует одну страницу через DashScope."""
    t0 = time.time()
    data = json.dumps({
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": SEMIOTIC_PROMPT},
        ]}],
        "max_tokens": 512,
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{DASHSCOPE_BASE}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read())
            result_text = raw["choices"][0]["message"]["content"]
    except Exception as e:
        return {
            "page_id": page_num,
            "primary_form": "discursive",
            "secondary_forms": [],
            "confidence": "LOW",
            "rationale": f"api_error: {e}",
            "elapsed_s": time.time() - t0,
        }

    elapsed = time.time() - t0

    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            parsed = json.loads(result_text[j1:j2])
            return {
                "page_id": page_num,
                "primary_form": parsed.get("primary_form", "discursive"),
                "secondary_forms": parsed.get("secondary_forms", []),
                "confidence": parsed.get("confidence", "LOW"),
                "rationale": parsed.get("rationale", ""),
                "elapsed_s": round(elapsed, 1),
            }
    except (json.JSONDecodeError, KeyError):
        pass

    return {
        "page_id": page_num,
        "primary_form": "discursive",
        "secondary_forms": [],
        "confidence": "LOW",
        "rationale": "parse_failed",
        "elapsed_s": round(elapsed, 1),
    }


def classify_document(pdf_path: str, dpi: int = 150, max_workers: int = MAX_WORKERS) -> dict:
    """Классифицирует все страницы документа через DashScope (параллельно)."""
    api_key = str(DASHSCOPE_KEY)
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # Рендерим все страницы
    page_images = []
    for page_num in range(total_pages):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()
        page_images.append((page_num + 1, img_b64))
    doc.close()

    print(f"  Cloud classify: {total_pages} стр. × {max_workers} workers (DashScope qwen3-vl-plus)")

    t0 = time.time()
    pages = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_classify_one, pn, img, api_key): pn
            for pn, img in page_images
        }
        for future in as_completed(futures):
            result = future.result()
            pages.append(result)
            print(f"    p{result['page_id']}: {result['primary_form']} ({result['confidence']}) — {result['elapsed_s']}s")

    # Сортируем по номерам страниц
    pages.sort(key=lambda p: p["page_id"])

    total_elapsed = time.time() - t0

    # Статистика форм
    form_counts = {}
    for p in pages:
        f = p["primary_form"]
        form_counts[f] = form_counts.get(f, 0) + 1

    print(f"  Cloud classify done: {total_elapsed:.1f}s total ({total_elapsed/total_pages:.1f}s/стр)")

    return {
        "pages": pages,
        "stats": {
            "total_pages": total_pages,
            "form_distribution": form_counts,
            "total_elapsed_s": round(total_elapsed, 1),
            "provider": "dashscope",
        },
    }