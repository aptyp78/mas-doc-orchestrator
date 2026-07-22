#!/usr/bin/env python3
"""OCR2 Pipeline с L1 Classifier — полный прогон документа.

Поток:
1. OCR2 (DeepSeek, 1-3s/стр) → блоки (text, table, image)
2. L1 Classifier (qwen3.6, ~30s/блок) → needs_vl?
3. VL (qwen3-vl, ~30s/блок) → только для needs_vl=true
4. L2 Extractors → схемы
5. L3 Ontology → онтология
6. L4 Reflector → рекомендации

Запуск:
  python3 scripts/run_ocr2_full_pipeline.py <pdf> [output_dir]
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import OLLAMA_LOCAL_BASE
from src.normalizer.ocr2_normalizer import _parse_ocr2_markdown
from src.normalizer.ocr2_classifier_heuristic import classify_image_block_heuristic as classify_image_block


def _call_ollama_generate(prompt: str, images: list[str] | None = None, max_tokens: int = 2048) -> str:
    """Вызов Ollama /api/generate (для VL)."""
    payload = {
        "model": "qwen3-vl:30b",
        "prompt": prompt,
        "stream": False,
    }
    if images:
        payload["images"] = images

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/generate", data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())["response"]


def _parse_json(text: str) -> dict:
    try:
        j1, j2 = text.find("{"), text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass
    return {}


def extract_vl_schema(image_b64: str, form_hint: str) -> dict:
    """Извлекает схему из image-блока через VL."""
    prompt = f"""[РОЛЬ] Экстрактор визуальной схемы
[ПРЕДМЕТ] {form_hint} на странице документа
[ЗАДАЧА] Извлеки структуру
[ПРАВИЛА]
1. Определи тип: topology, spatial, hierarchy, dynamics
2. Извлеки ВСЕ элементы, метрики, названия
3. Извлеки вывод/заголовок
[ОГРАНИЧЕНИЕ] Не интерпретируй. Извлекай ВСЕ элементы.

Формат: JSON
{{
  "form": "topology|spatial|hierarchy|dynamics",
  "sets": [{{"name": "string", "elements": ["string"]}}],
  "metrics": [{{"label": "string", "value": "string"}}],
  "page_title": "string",
  "conclusion": "string"
}}"""

    result = _call_ollama_generate(prompt, images=[image_b64])
    return _parse_json(result)


def run_ocr2_full_pipeline(pdf_path: str, output_dir: str | None = None, dpi: int = 200):
    """Полный OCR2-пайплайн с L1 Classifier."""
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
    vl_count = 0
    skip_count = 0

    print(f"OCR2 Full Pipeline: {total_pages} pages")
    print("=" * 60)

    # Загружаем OCR2 результаты из кэша (если есть)
    ocr2_cache = {}
    cache_path = "/tmp/iafr_ocr_results.json"
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            ocr2_cache = json.load(f)
        print(f"Loaded {len(ocr2_cache)} OCR2 results from cache")

    for i in range(total_pages):
        page = doc[i]
        page_num = i + 1
        pix = page.get_pixmap(dpi=dpi)
        png_path = f"/tmp/ocr2_page_{page_num}.png"
        pix.save(png_path)

        # OCR2 (из кэша или MCP)
        if str(page_num) in ocr2_cache:
            result = ocr2_cache[str(page_num)]
            if isinstance(result, dict) and "result" in result:
                markdown = result["result"]
            else:
                markdown = str(result)
        else:
            # TODO: Call MCP OCR2 here
            markdown = ""
            print(f"  p{page_num}: NO OCR2 RESULT (cache miss)")
            continue

        # Парсинг блоков
        blocks = _parse_ocr2_markdown(markdown, page_num)
        block_types = {b.block_type for b in blocks}
        form = "matrix" if "table" in block_types else "discursive" if "text" in block_types else "mixed"

        # Извлечение текста
        text_content = " ".join(b.content for b in blocks if b.content.strip())[:2000]

        # Обработка image-блоков через L1 Classifier
        image_schemas = []
        for block in blocks:
            if block.block_type == "image":
                # Собираем контекст
                surrounding = " ".join(b.content for b in blocks if b.block_type == "text")[:300]

                # L1 Classifier
                classification = classify_image_block(block.bbox, surrounding, form)

                if classification.needs_vl:
                    # VL extraction
                    with open(png_path, "rb") as f:
                        img_b64 = base64.b64encode(f.read()).decode()

                    vl_schema = extract_vl_schema(img_b64, classification.visual_form)
                    if vl_schema:
                        image_schemas.append(vl_schema)
                        vl_count += 1
                        print(f"  p{page_num} image: VL → {classification.visual_form} (conf={classification.confidence:.2f})")
                else:
                    skip_count += 1
                    print(f"  p{page_num} image: SKIP ({classification.visual_form}, conf={classification.confidence:.2f})")

        # Сборка схемы
        schema = {
            "page_id": page_num,
            "form": form,
            "full_text": text_content,
        }

        # Добавляем заголовок
        for block in blocks:
            if block.block_type == "sub_title" and block.content.strip():
                schema["page_title"] = block.content.strip()[:200]
                break

        # Добавляем VL схемы
        if image_schemas:
            schema["zone_schemas"] = {f"zone_{i}": s for i, s in enumerate(image_schemas)}

        # Добавляем таблицы
        for block in blocks:
            if block.block_type == "table" and "<table>" in block.content:
                import re
                rows = re.findall(r'<tr>(.*?)</tr>', block.content, re.DOTALL)
                schema["columns"] = []
                schema["rows"] = []
                for j, row in enumerate(rows):
                    cells = re.findall(r'<td>(.*?)</td>', row)
                    if j == 0:
                        schema["columns"] = [c.strip() for c in cells]
                    else:
                        schema["rows"].append({"label": cells[0].strip() if cells else "", "cells": [c.strip() for c in cells[1:]]})

        pages_form[page_num] = form
        schemas[page_num] = schema
        print(f"  p{page_num}: {form} ({len(blocks)} blocks, {len(image_schemas)} VL)")

    doc.close()

    # Сохраняем
    with open(f"{output_dir}/01_ocr2_classification.json", "w") as f:
        form_dist = {}
        for f in pages_form.values():
            form_dist[f] = form_dist.get(f, 0) + 1
        json.dump({"pages": [{"page_id": p, "primary_form": f} for p, f in sorted(pages_form.items())],
                   "stats": {"form_distribution": form_dist, "total_pages": total_pages,
                             "vl_blocks": vl_count, "skipped_blocks": skip_count}},
                  f, ensure_ascii=False, indent=2)

    with open(f"{output_dir}/03_schemas.json", "w") as f:
        json.dump(schemas, f, ensure_ascii=False, indent=2)

    total_elapsed = time.time() - t_total

    print(f"\n{'=' * 60}")
    print(f"OCR2 FULL PIPELINE COMPLETE: {total_elapsed:.1f}s")
    print(f"  Pages: {total_pages}")
    print(f"  VL blocks: {vl_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Forms: {form_dist}")
    print(f"  Results: {output_dir}/")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/run_ocr2_full_pipeline.py <file> [output_dir]")
        print("Supported formats: PDF, PPTX, DOCX, PNG, JPG, HTML, MD")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Format Detector Agent: определяем формат и конвертируем если нужно
    print("\n[Format Detector Agent]")
    from src.ingestion.format_detector import prepare_for_pipeline
    pdf_path = prepare_for_pipeline(input_path)
    print(f"Ready for pipeline: {pdf_path}")
    
    print(f"\n[OCR2 Full Pipeline]")
    run_ocr2_full_pipeline(pdf_path, output_dir)