#!/usr/bin/env python3
"""OCR2 Pipeline — полный конвейер на DeepSeek OCR2.

Заменяет Cloud-зависимый пайплайн на полностью локальный:
  PDF → OCR2 (1-3s/стр) → block classifier → extractors → онтология → рефлексия

VL-модель (qwen3-vl) используется ТОЛЬКО для image-блоков (~6 стр. из 81).
Остальное — текст и таблицы — обрабатывается без VL.

Запуск:
  python3 scripts/run_ocr2_pipeline.py <pdf> [output_dir]
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import OLLAMA_LOCAL_BASE

# ═══════════════════════════════════════════════════════════
# OCR2 Normalizer (inline — не требует MCP, работает через HTTP)
# ═══════════════════════════════════════════════════════════

OCR2_ENDPOINT = "http://127.0.0.1:5100/call"


def ocr2_page(png_path: str) -> dict:
    """Вызывает DeepSeek OCR2 через MCP HTTP endpoint."""
    try:
        data = json.dumps({"file_path": png_path, "mode": "markdown"}).encode()
        req = urllib.request.Request(
            OCR2_ENDPOINT, data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"result": "", "duration_seconds": 0}


def parse_ocr2_blocks(markdown: str, page_num: int) -> dict:
    """Парсит markdown OCR2 в классифицированные блоки."""
    blocks = {"sub_title": [], "text": [], "table": [], "image": [], "raw": markdown}

    pattern = re.compile(
        r'<\|ref\|>(.*?)<\|/ref\|>\s*<\|det\|>\[(.*?)\]\s*<\|/det\|>\s*\n(.*?)(?=\n<\|ref\|>|$)',
        re.DOTALL,
    )

    for match in pattern.finditer(markdown):
        block_type = match.group(1).strip()
        coords_str = match.group(2).strip()
        content = match.group(3).strip()

        bboxes = []
        for cm in re.finditer(r'\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]', coords_str):
            bboxes.append([int(cm.group(i)) for i in range(1, 5)])

        blocks[block_type].append({
            "type": block_type, "content": content, "bbox": bboxes[0] if bboxes else [0, 0, 0, 0],
        })

    return blocks


# ═══════════════════════════════════════════════════════════
# Block → SMD Form Classifier
# ═══════════════════════════════════════════════════════════

def classify_page_form(blocks: dict) -> str:
    """Определяет SMD-форму страницы по типам блоков."""
    has_image = len(blocks["image"]) > 0
    has_table = len(blocks["table"]) > 0
    has_subtitle = len(blocks["sub_title"]) > 0
    text_count = len(blocks["text"])

    if has_table and has_image:
        return "mixed"
    if has_table:
        return "matrix"
    if has_image:
        return "mixed"  # image + text → mixed
    if text_count <= 3:
        return "discursive"
    if text_count <= 8:
        return "enumeration"
    return "discursive"


# ═══════════════════════════════════════════════════════════
# Schema Extraction
# ═══════════════════════════════════════════════════════════

def extract_schema_from_blocks(blocks: dict, page_num: int) -> dict:
    """Извлекает схему из блоков OCR2."""
    schema = {"page_id": page_num, "form": classify_page_form(blocks)}

    # Заголовок из sub_title
    for st in blocks["sub_title"]:
        content = st["content"].lstrip("#").strip()
        if content and len(content) > 5:
            schema["page_title"] = content
            break

    # Текст из text-блоков
    all_text = []
    for t in blocks["text"]:
        content = t["content"].strip()
        if content:
            all_text.append(content)
    schema["full_text"] = "\n\n".join(all_text)

    # Ключевые тезисы (первые 3 непустых текстовых блока)
    key_theses = [t for t in all_text if len(t) > 20][:5]
    schema["key_theses"] = key_theses

    # Вывод — последний значимый текстовый блок
    significant = [t for t in all_text if len(t) > 30]
    if significant:
        schema["conclusion"] = significant[-1]

    # Таблицы → rows
    for tbl in blocks["table"]:
        content = tbl["content"]
        if "<table>" in content:
            rows = re.findall(r'<tr>(.*?)</tr>', content, re.DOTALL)
            schema["columns"] = []
            schema["rows"] = []
            for i, row in enumerate(rows):
                cells = re.findall(r'<td>(.*?)</td>', row)
                if i == 0:
                    schema["columns"] = [c.strip() for c in cells]
                else:
                    schema["rows"].append({"label": cells[0].strip() if cells else "", "cells": [c.strip() for c in cells[1:]]})

    # Image-блоки → требуют VL
    schema["image_blocks"] = len(blocks["image"])
    schema["needs_vl"] = len(blocks["image"]) > 0

    return schema


# ═══════════════════════════════════════════════════════════
# VL Extractor (только для image-блоков)
# ═══════════════════════════════════════════════════════════

def extract_vl_schema(png_path: str) -> dict:
    """Извлекает схему из image-блока через локальную VL-модель."""
    import base64

    with open(png_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    prompt = """[РОЛЬ] Экстрактор визуальной схемы
[ПРЕДМЕТ] Диаграмма/схема/карта на странице
[ЗАДАЧА] Извлеки структуру
[ПРАВИЛА]
1. Определи тип: topology (диаграмма), spatial (карта), hierarchy (пирамида), dynamics (график)
2. Извлеки ВСЕ элементы, метрики, названия
3. Извлеки вывод/заголовок
[ОГРАНИЧЕНИЕ] Не интерпретируй. Извлекай ВСЕ элементы.

Формат: JSON
{
  "form": "topology|spatial|hierarchy|dynamics",
  "sets": [{"name": "string", "elements": ["string"]}],
  "metrics": [{"label": "string", "value": "string"}],
  "page_title": "string",
  "conclusion": "string"
}"""

    data = json.dumps({
        "model": "qwen3-vl:30b",
        "prompt": prompt,
        "images": [img_b64],
        "stream": False,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_LOCAL_BASE}/api/generate", data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = json.loads(resp.read())
            text = raw["response"]
            j1, j2 = text.find("{"), text.rfind("}") + 1
            if j1 >= 0 and j2 > j1:
                return json.loads(text[j1:j2])
    except Exception:
        pass
    return {"form": "image", "error": "vl_failed"}


# ═══════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════

def run_ocr2_pipeline(pdf_path: str, output_dir: str | None = None, dpi: int = 200):
    """Полный OCR2-конвейер."""
    import fitz

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    if output_dir is None:
        ts = time.strftime("%Y-%m-%d_%H%M")
        output_dir = f"output/run_ocr2_{ts}"
    os.makedirs(output_dir, exist_ok=True)

    t_total = time.time()
    pages_form = {}
    schemas = {}
    vl_pages = []

    print(f"OCR2 Pipeline: {total_pages} pages")
    print("=" * 60)

    # Фаза 1: OCR2 всех страниц + классификация
    print("\n[1/3] OCR2 нормализация...")
    t_ocr = time.time()

    for i in range(total_pages):
        page = doc[i]
        pix = page.get_pixmap(dpi=dpi)
        png_path = f"/tmp/ocr2_p{page.number + 1}.png"
        pix.save(png_path)

        # OCR2
        result = ocr2_page(png_path)
        markdown = result.get("result", "")
        ocr_time = result.get("duration_seconds", 0)

        # Парсинг
        blocks = parse_ocr2_blocks(markdown, page.number + 1)
        form = classify_page_form(blocks)
        schema = extract_schema_from_blocks(blocks, page.number + 1)

        pages_form[page.number + 1] = form
        schemas[page.number + 1] = schema

        if schema["needs_vl"]:
            vl_pages.append(page.number + 1)

        n_text = len(blocks["text"])
        n_table = len(blocks["table"])
        n_img = len(blocks["image"])
        print(f"  p{page.number+1}: {form} ({n_text}t/{n_table}tbl/{n_img}img) — {ocr_time:.1f}s")

    doc.close()
    ocr_elapsed = time.time() - t_ocr
    print(f"  OCR2 done: {ocr_elapsed:.1f}s ({ocr_elapsed/total_pages:.1f}s/стр)")

    # Фаза 2: VL для image-блоков
    if vl_pages:
        print(f"\n[2/3] VL extraction for {len(vl_pages)} image pages...")
        t_vl = time.time()

        for pn in vl_pages:
            png_path = f"/tmp/ocr2_p{pn}.png"
            if not os.path.exists(png_path):
                continue
            vl_schema = extract_vl_schema(png_path)
            form = vl_schema.get("form", "image")
            # Обновляем схему
            schemas[pn].update(vl_schema)
            schemas[pn]["form"] = form
            pages_form[pn] = form
            print(f"  p{pn}: VL → {form}")

        vl_elapsed = time.time() - t_vl
        print(f"  VL done: {vl_elapsed:.1f}s")
    else:
        vl_elapsed = 0

    # Сохраняем
    with open(f"{output_dir}/01_ocr2_classification.json", "w") as f:
        form_dist = {}
        for f in pages_form.values():
            form_dist[f] = form_dist.get(f, 0) + 1
        json.dump({"pages": [{"page_id": p, "primary_form": f} for p, f in sorted(pages_form.items())],
                   "stats": {"form_distribution": form_dist, "total_pages": total_pages,
                             "ocr2_elapsed_s": round(ocr_elapsed, 1), "vl_elapsed_s": round(vl_elapsed, 1)}},
                  f, ensure_ascii=False, indent=2)

    with open(f"{output_dir}/03_schemas.json", "w") as f:
        json.dump(schemas, f, ensure_ascii=False, indent=2)

    total_elapsed = time.time() - t_total

    print(f"\n{'=' * 60}")
    print(f"OCR2 PIPELINE COMPLETE: {total_elapsed:.1f}s ({total_elapsed/total_pages:.1f}s/стр)")
    print(f"  OCR2: {ocr_elapsed:.1f}s")
    print(f"  VL:   {vl_elapsed:.1f}s")
    print(f"  Forms: {form_dist}")
    print(f"  Results: {output_dir}/")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/run_ocr2_pipeline.py <pdf> [output_dir]")
        sys.exit(1)
    run_ocr2_pipeline(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)