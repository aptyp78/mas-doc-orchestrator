"""Уровень 1.5: Декомпозиция mixed-страниц.

Для страниц с primary_form="mixed" определяет суб-формы в каждой визуальной зоне.
Использует qwen3-vl-plus (Cloud) для разбора страницы на регионы.

Пример: страница с Venn-диаграммой + текстовым выводом → два региона:
  {zone: "top", form: "topology", ...}, {zone: "bottom", form: "discursive", ...}
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

DECOMPOSE_PROMPT = load_prompt("semiotic/mixed_decomposer")


def _decompose_one(page_num: int, img_b64: str, api_key: str) -> dict:
    """Декомпозирует одну mixed-страницу."""
    t0 = time.time()

    data = json.dumps({
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": DECOMPOSE_PROMPT},
        ]}],
        "max_tokens": 1024,
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
            "zones": [],
            "overall_structure": f"api_error: {e}",
            "elapsed_s": time.time() - t0,
        }

    elapsed = time.time() - t0

    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            parsed = json.loads(result_text[j1:j2])
            parsed["page_id"] = page_num
            parsed["elapsed_s"] = round(elapsed, 1)
            return parsed
    except (json.JSONDecodeError, KeyError):
        pass

    return {
        "page_id": page_num,
        "zones": [],
        "overall_structure": "parse_failed",
        "elapsed_s": round(elapsed, 1),
    }


def decompose_mixed(
    classification: dict,
    pdf_path: str,
    dpi: int = 150,
    max_workers: int = MAX_WORKERS,
) -> dict:
    """Декомпозирует все mixed-страницы на суб-формы.

    Returns:
        {page_id: {zones: [...], overall_structure: "..."}}
    """
    api_key = str(DASHSCOPE_KEY)
    mixed_pages = [
        p for p in classification["pages"]
        if p["primary_form"] == "mixed"
    ]

    if not mixed_pages:
        print("  Mixed decomposer: нет mixed-страниц")
        return {}

    print(f"  Mixed decomposer: {len(mixed_pages)} mixed-стр. × {max_workers} workers")

    doc = fitz.open(pdf_path)
    t0 = time.time()

    # Рендерим mixed-страницы
    tasks = []
    for p in mixed_pages:
        page = doc[p["page_id"] - 1]
        pix = page.get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()
        tasks.append((p["page_id"], img_b64))
    doc.close()

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_decompose_one, pn, img, api_key): pn
            for pn, img in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            results[result["page_id"]] = result
            zones = result.get("zones", [])
            zone_forms = [z["form"] for z in zones]
            print(f"    p{result['page_id']}: {len(zones)} zones → {zone_forms} — {result.get('elapsed_s', '?')}s")

    total_elapsed = time.time() - t0
    print(f"  Mixed decomposer done: {total_elapsed:.1f}s total")

    return results