#!/usr/bin/env python3
"""Бенчмарк трёх подходов к image-only страницам.

A: Cloud hybrid — DashScope qwen3-vl-plus (4 параллельных)
B: Tesseract-first — OCR → vision только если текст не извлечён
C: Vision-batching — несколько страниц в одном запросе к Ollama

Запуск: python3 scripts/benchmark_vision.py
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OLLAMA_BASE = "http://localhost:11434"
DASHSCOPE_ENDPOINT = "https://ws-yrwako2ivay84n1p.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1/chat/completions"

TEST_PDFS = [
    "data/docs/карта.pdf",
    "data/docs/ЦОД+ПАК.pdf",
]

# ═══════════════════════════════════════════════════════════════
# Подготовка: рендерим все image-only страницы
# ═══════════════════════════════════════════════════════════════

def collect_image_pages(pdf_paths: list[str]) -> list[dict]:
    """Собирает image-only страницы из PDF."""
    pages = []
    for pdf_path in pdf_paths:
        if not os.path.exists(pdf_path):
            continue
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text().strip()
            images = page.get_images(full=True)
            if not text and images:
                pix = page.get_pixmap(dpi=150)
                img_b64 = base64.b64encode(pix.tobytes("png")).decode()
                pages.append({
                    "pdf": os.path.basename(pdf_path),
                    "page_num": page_num + 1,
                    "img_b64": img_b64,
                    "width": int(page.rect.width),
                    "height": int(page.rect.height),
                })
        doc.close()
    return pages


def get_dashscope_key() -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-a", "dashscope-modelstudio", "-w"],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


# ═══════════════════════════════════════════════════════════════
# A: Cloud Hybrid
# ═══════════════════════════════════════════════════════════════

EXTRACT_PROMPT = "Извлеки весь текст с этого изображения дословно. Только текст, без описания."

def _call_cloud_vision(img_b64: str, api_key: str) -> dict:
    t0 = time.time()
    data = json.dumps({
        "model": "qwen3-vl-plus",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": EXTRACT_PROMPT},
        ]}],
        "max_tokens": 1024,
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        DASHSCOPE_ENDPOINT, data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = json.loads(resp.read())
        text = raw["choices"][0]["message"]["content"]
    elapsed = time.time() - t0
    return {"text": text, "time_s": round(elapsed, 1), "chars": len(text)}


def benchmark_cloud(pages: list[dict], max_workers: int = 4) -> dict:
    """A: Cloud hybrid — параллельные запросы к DashScope."""
    api_key = get_dashscope_key()
    if not api_key:
        return {"error": "no_api_key", "time_s": 0}

    print(f"\n── A: Cloud Hybrid (DashScope, {max_workers} workers) ──")
    t0 = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_call_cloud_vision, p["img_b64"], api_key): p for p in pages}
        for future in as_completed(futures):
            page = futures[future]
            try:
                r = future.result()
                results.append({**page, **r})
                print(f"  {page['pdf']} p{page['page_num']}: {r['time_s']}s, {r['chars']} chars")
            except Exception as e:
                results.append({**page, "error": str(e)})
                print(f"  {page['pdf']} p{page['page_num']}: ERROR {e}")

    total_s = time.time() - t0
    success = sum(1 for r in results if "error" not in r)
    avg_time = sum(r.get("time_s", 0) for r in results) / max(len(results), 1)
    print(f"  Total: {total_s:.1f}s, success: {success}/{len(pages)}, avg/page: {avg_time:.1f}s")
    return {"total_s": round(total_s, 1), "success": success, "total": len(pages), "avg_per_page_s": round(avg_time, 1)}


# ═══════════════════════════════════════════════════════════════
# B: Tesseract-first
# ═══════════════════════════════════════════════════════════════

def _tesseract_page(page: dict) -> dict:
    t0 = time.time()
    img_bytes = base64.b64decode(page["img_b64"])
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(img_bytes)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["tesseract", tmp_path, "stdout", "-l", "rus+eng", "--psm", "6"],
            capture_output=True, text=True, timeout=60,
        )
        text = result.stdout.strip()
    finally:
        os.unlink(tmp_path)

    elapsed = time.time() - t0
    return {"text": text, "time_s": round(elapsed, 1), "chars": len(text), "source": "tesseract"}


def _ollama_vision_if_needed(page: dict, tesseract_result: dict) -> dict:
    """Вызывает vision model только если Tesseract не справился."""
    if tesseract_result["chars"] >= 20:
        return tesseract_result

    # Vision model
    t0 = time.time()
    data = json.dumps({
        "model": "qwen3-vl:30b",
        "prompt": EXTRACT_PROMPT,
        "images": [page["img_b64"]],
        "stream": False,
    }).encode()

    req = urllib.request.Request(f"{OLLAMA_BASE}/api/generate", data=data,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = json.loads(resp.read())
        text = raw["response"]

    elapsed = time.time() - t0
    return {"text": text, "time_s": round(elapsed, 1), "chars": len(text), "source": "vision"}


def benchmark_tesseract_first(pages: list[dict]) -> dict:
    """B: Tesseract-first — OCR, vision только если нужно."""
    print("\n── B: Tesseract-first ──")
    t0 = time.time()
    results = []

    for page in pages:
        ts = _tesseract_page(page)
        if ts["chars"] >= 20:
            results.append({**page, **ts})
            print(f"  {page['pdf']} p{page['page_num']}: Tesseract {ts['time_s']}s, {ts['chars']} chars ✅")
        else:
            vs = _ollama_vision_if_needed(page, ts)
            results.append({**page, **ts, "vision_fallback": vs})
            total_s = ts["time_s"] + vs.get("time_s", 0)
            print(f"  {page['pdf']} p{page['page_num']}: Tesseract {ts['time_s']}s → Vision {vs.get('time_s',0)}s = {total_s:.1f}s")

    total_s = time.time() - t0
    tesseract_only = sum(1 for r in results if r.get("source") == "tesseract")
    vision_fallbacks = len(results) - tesseract_only
    print(f"  Total: {total_s:.1f}s, Tesseract-only: {tesseract_only}, Vision fallbacks: {vision_fallbacks}")
    return {"total_s": round(total_s, 1), "tesseract_only": tesseract_only, "vision_fallbacks": vision_fallbacks}


# ═══════════════════════════════════════════════════════════════
# C: Vision-batching
# ═══════════════════════════════════════════════════════════════

def benchmark_vision_batch(pages: list[dict], batch_size: int = 3) -> dict:
    """C: Vision-batching — несколько страниц в одном запросе."""
    print(f"\n── C: Vision-batching (batch_size={batch_size}) ──")
    t0 = time.time()
    results = []

    for i in range(0, len(pages), batch_size):
        batch = pages[i : i + batch_size]
        images = [p["img_b64"] for p in batch]
        labels = "\n".join(
            f"Страница {p['page_num']} ({p['pdf']})" for p in batch
        )
        prompt = f"{EXTRACT_PROMPT}\n\nДокументы:\n{labels}\n\nДля каждой страницы извлеки текст отдельно. Формат: 'Страница N: <текст>'"

        t_call = time.time()
        data = json.dumps({
            "model": "qwen3-vl:30b",
            "prompt": prompt,
            "images": images,
            "stream": False,
        }).encode()

        try:
            req = urllib.request.Request(f"{OLLAMA_BASE}/api/generate", data=data,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as resp:
                raw = json.loads(resp.read())
                text = raw["response"]
            elapsed = time.time() - t_call
            for p in batch:
                results.append({**p, "text": text[:500], "time_s": round(elapsed / len(batch), 1), "chars": len(text), "source": "vision_batch"})
            print(f"  Batch {i//batch_size + 1}: {len(batch)} стр. → {elapsed:.1f}s ({elapsed/len(batch):.1f}s/стр)")
        except Exception as e:
            print(f"  Batch {i//batch_size + 1}: ERROR {e}")
            for p in batch:
                results.append({**p, "error": str(e)})

    total_s = time.time() - t0
    success = sum(1 for r in results if "error" not in r)
    print(f"  Total: {total_s:.1f}s, success: {success}/{len(pages)}")
    return {"total_s": round(total_s, 1), "success": success, "total": len(pages)}


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 55)
    print("БЕНЧМАРК: ТРИ ПОДХОДА К IMAGE-ONLY СТРАНИЦАМ")
    print("=" * 55)

    # Собираем страницы
    pages = collect_image_pages(TEST_PDFS)
    print(f"\nImage-only страниц: {len(pages)}")
    for p in pages:
        print(f"  {p['pdf']} p{p['page_num']}: {p['width']}×{p['height']}")

    if not pages:
        print("Нет image-only страниц для теста")
        return

    results = {}

    # A: Cloud
    results["A_cloud"] = benchmark_cloud(pages, max_workers=4)

    # B: Tesseract-first
    results["B_tesseract"] = benchmark_tesseract_first(pages)

    # C: Vision-batching
    results["C_vision_batch"] = benchmark_vision_batch(pages, batch_size=min(3, len(pages)))

    # Сводка
    print("\n" + "=" * 55)
    print("СВОДНАЯ ТАБЛИЦА")
    print("=" * 55)
    print(f"{'Подход':<25} {'Время':>8} {'Успех':>8} {'Примечание'}")
    print("-" * 55)

    for name, r in results.items():
        label = {
            "A_cloud": "A: Cloud (DashScope)",
            "B_tesseract": "B: Tesseract-first",
            "C_vision_batch": "C: Vision-batching",
        }.get(name, name)
        ts = r.get("total_s", 0)
        succ = f"{r.get('success', r.get('tesseract_only', '?'))}/{r.get('total', '?')}"
        note = ""
        if name == "A_cloud":
            note = f"avg {r.get('avg_per_page_s', '?')}s/стр"
        elif name == "B_tesseract":
            note = f"vision fallbacks: {r.get('vision_fallbacks', 0)}"
        print(f"{label:<25} {ts:>7.1f}s {succ:>8}  {note}")

    # Сохраняем
    out = Path("output/benchmark_vision.json")
    out.parent.mkdir(exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nСохранено: {out}")


if __name__ == "__main__":
    main()