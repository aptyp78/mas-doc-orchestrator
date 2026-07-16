#!/usr/bin/env python3
"""Полный Cloud-пайплайн: 81 страница за ~6-8 минут.

P0: Cloud (DashScope) классификация всех 81 страниц
P1: Cloud (DashScope) ontology + reflector
P2: Mixed page decomposition
P3: Дашборд

Запуск:
  python3 scripts/run_cloud_pipeline.py data/docs/Презентация_ИАфр_РАН_финал.pdf
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.semiotic.cloud_classifier import classify_document, SEMIOTIC_PROMPT
from src.semiotic.cloud_ontology import map_all as ontology_map_all
from src.semiotic.cloud_reflector import reflect_all as reflector_reflect_all
from src.semiotic.mixed_decomposer import decompose_mixed
from src.semiotic.extractors import (
    VENN_PROMPT, HIERARCHY_PROMPT, MATRIX_PROMPT, ENUMERATION_PROMPT,
)
from src.utils.config import DASHSCOPE_KEY, DASHSCOPE_BASE

VISION_MODEL = "qwen3-vl-plus"
TEXT_MODEL = "qwen3.7-plus"
MAX_WORKERS = 8

# ═══════════════════════════════════════════════════════════════
# Schema extraction for visual pages
# ═══════════════════════════════════════════════════════════════

EXTRACTOR_PROMPTS = {
    "topology": VENN_PROMPT,
    "hierarchy": HIERARCHY_PROMPT,
    "matrix": MATRIX_PROMPT,
    "enumeration": ENUMERATION_PROMPT,
    "spatial": """[РОЛЬ] Экстрактор пространственной схемы
[ПРЕДМЕТ] Страница с географической картой / территорией
[ЗАДАЧА] Извлеки структуру как пространственную схему
[ПРАВИЛА]
1. Перечисли ВСЕ регионы/зоны/страны на карте
2. Для каждого — ключевые характеристики (метрики, подписи)
3. Извлеки легенду карты
4. Извлеки заголовок и вывод страницы
[ОГРАНИЧЕНИЕ] Не интерпретируй. Извлекай ВСЕ элементы.

Формат: JSON
{
  "regions": [{"name": "string", "metrics": {}, "labels": []}],
  "legend": {},
  "page_title": "string",
  "conclusion": "string"
}""",
    "dynamics": """[РОЛЬ] Экстрактор динамической схемы
[ПРЕДМЕТ] Страница с графиком / кривой / осями координат
[ЗАДАЧА] Извлеки структуру как схему функционально-временной динамики
[ПРАВИЛА]
1. Определи оси (X, Y) — что измеряется
2. Извлеки ВСЕ кривые/тренды — название, направление
3. Извлеки ключевые точки (пики, спады, пересечения)
4. Извлеки заголовок и вывод страницы
[ОГРАНИЧЕНИЕ] Не интерпретируй. Извлекай ВСЕ элементы.

Формат: JSON
{
  "axes": {"x": "string", "y": "string"},
  "curves": [{"name": "string", "direction": "up|down|flat", "key_points": []}],
  "page_title": "string",
  "conclusion": "string"
}""",
}


def _extract_visual_schema(page_num: int, img_b64: str, form: str, api_key: str) -> dict:
    """Извлекает схему из визуальной страницы через Cloud vision."""
    t0 = time.time()
    prompt = EXTRACTOR_PROMPTS.get(form, EXTRACTOR_PROMPTS["enumeration"])

    data = json.dumps({
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": 2048,
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{DASHSCOPE_BASE}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = json.loads(resp.read())
            result_text = raw["choices"][0]["message"]["content"]
    except Exception as e:
        return {"page_id": page_num, "form": form, "error": str(e), "elapsed_s": time.time() - t0}

    elapsed = time.time() - t0

    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            parsed = json.loads(result_text[j1:j2])
            parsed["page_id"] = page_num
            parsed["form"] = form
            parsed["elapsed_s"] = round(elapsed, 1)
            return parsed
    except (json.JSONDecodeError, KeyError):
        pass

    return {"page_id": page_num, "form": form, "raw_text": result_text[:500], "elapsed_s": round(elapsed, 1)}


# ═══════════════════════════════════════════════════════════════
# OCR-based text extraction for discursive pages
# ═══════════════════════════════════════════════════════════════

def _extract_text_discursive(page_num: int, img_b64: str, api_key: str) -> dict:
    """Извлекает структуру discursive-страницы через Cloud vision OCR."""
    t0 = time.time()

    prompt = """[РОЛЬ] Экстрактор дискурсивной структуры
[ПРЕДМЕТ] Страница со сплошным текстом
[ЗАДАЧА] Извлеки структуру аргументации
[ПРАВИЛА]
1. Извлеки заголовок/тему страницы
2. Выдели ключевые тезисы (3-5)
3. Извлеки вывод/заключение страницы
4. Перечисли ключевые термины/сущности
[ОГРАНИЧЕНИЕ] Только структура. Не интерпретируй содержание.

Формат: JSON
{
  "title": "string",
  "key_theses": ["string", ...],
  "conclusion": "string",
  "key_terms": ["string", ...],
  "full_text": "string"
}"""

    data = json.dumps({
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": 2048,
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{DASHSCOPE_BASE}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read())
            result_text = raw["choices"][0]["message"]["content"]
    except Exception as e:
        return {"page_id": page_num, "form": "discursive", "error": str(e), "elapsed_s": time.time() - t0}

    elapsed = time.time() - t0

    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            parsed = json.loads(result_text[j1:j2])
            parsed["page_id"] = page_num
            parsed["form"] = "discursive"
            parsed["elapsed_s"] = round(elapsed, 1)
            return parsed
    except (json.JSONDecodeError, KeyError):
        pass

    return {"page_id": page_num, "form": "discursive", "full_text": result_text[:500], "elapsed_s": round(elapsed, 1)}


# ═══════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════

def run_full_pipeline(pdf_path: str, output_dir: str | None = None, dpi: int = 150):
    """Полный 4-уровневый пайплайн: Классификация → Схема → Онтология → Рефлексия."""
    api_key = str(DASHSCOPE_KEY)
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    print(f"PDF: {total_pages} страниц")

    # Создаём output-директорию
    if output_dir is None:
        ts = time.strftime("%Y-%m-%d_%H%M")
        output_dir = f"output/run_{ts}"
    os.makedirs(output_dir, exist_ok=True)

    t_total = time.time()

    # ═══════════════════════════════════════════════════════════
    # УРОВЕНЬ 1: Семиотическая классификация (Cloud)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("УРОВЕНЬ 1: Семиотическая классификация (Cloud)")
    print("=" * 60)

    classification = classify_document(pdf_path, dpi=dpi, max_workers=MAX_WORKERS)

    with open(f"{output_dir}/01_semiotic_classification.json", "w") as f:
        json.dump(classification, f, ensure_ascii=False, indent=2)

    # Статистика
    dist = classification["stats"]["form_distribution"]
    print(f"\n  Распределение форм:")
    for form, count in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"    {form}: {count} стр.")

    # ═══════════════════════════════════════════════════════════
    # P2: Mixed page decomposition
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("P2: Mixed page decomposition (Cloud)")
    print("=" * 60)

    mixed_decompositions = decompose_mixed(classification, pdf_path, dpi=dpi)

    with open(f"{output_dir}/02_mixed_decomposition.json", "w") as f:
        json.dump(mixed_decompositions, f, ensure_ascii=False, indent=2)

    # ═══════════════════════════════════════════════════════════
    # УРОВЕНЬ 2: Извлечение схем (Cloud vision)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("УРОВЕНЬ 2: Извлечение схем (Cloud vision)")
    print("=" * 60)

    # Рендерим все страницы для экстракции
    page_images = {}
    for page_num in range(total_pages):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode()
        page_images[page_num + 1] = img_b64

    # Определяем, какие страницы требуют визуальной экстракции
    visual_forms = {"topology", "matrix", "hierarchy", "spatial", "enumeration", "dynamics"}
    schemas = {}

    visual_tasks = []
    discursive_tasks = []
    empty_pages = []

    for p in classification["pages"]:
        pid = p["page_id"]
        form = p["primary_form"]

        if form == "empty":
            empty_pages.append(pid)
            schemas[pid] = {"page_id": pid, "form": "empty", "empty": True}
        elif form in visual_forms:
            visual_tasks.append((pid, form))
        elif form == "mixed":
            # Mixed: используем decomposition для определения суб-форм
            decomp = mixed_decompositions.get(pid, {})
            zones = decomp.get("zones", [])
            if zones:
                # Берём приоритетную зону для экстракции
                priority_zones = sorted(zones, key=lambda z: z.get("priority", 3))
                schemas[pid] = {
                    "page_id": pid,
                    "form": "mixed",
                    "zones": zones,
                    "overall_structure": decomp.get("overall_structure", ""),
                }
                # Добавляем визуальные зоны на экстракцию
                for z in zones:
                    if z["form"] in visual_forms:
                        visual_tasks.append((pid, z["form"]))
            else:
                discursive_tasks.append(pid)
        else:  # discursive
            discursive_tasks.append(pid)

    # Экстракция визуальных схем (параллельно)
    if visual_tasks:
        print(f"  Visual schema extraction: {len(visual_tasks)} задач")
        vid_map = {}
        for pid, form in visual_tasks:
            key = f"{pid}_{form}"
            vid_map[key] = (pid, form)

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for pid, form in set(visual_tasks):
                future = executor.submit(_extract_visual_schema, pid, page_images[pid], form, api_key)
                futures[future] = (pid, form)

            for future in as_completed(futures):
                result = future.result()
                pid = result["page_id"]
                form = result.get("form", "?")

                if pid not in schemas or schemas[pid].get("form") != "mixed":
                    schemas[pid] = result
                else:
                    # Mixed: добавляем схему зоны
                    if "zone_schemas" not in schemas[pid]:
                        schemas[pid]["zone_schemas"] = {}
                    schemas[pid]["zone_schemas"][form] = result

                elapsed = result.get("elapsed_s", "?")
                print(f"    p{pid} [{form}]: extracted — {elapsed}s")

        print(f"  Visual extraction done: {time.time() - t0:.1f}s")

    # Экстракция discursive-страниц (параллельно)
    if discursive_tasks:
        print(f"  Discursive extraction: {len(discursive_tasks)} задач")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_extract_text_discursive, pid, page_images[pid], api_key): pid
                for pid in discursive_tasks
            }
            for future in as_completed(futures):
                result = future.result()
                pid = result["page_id"]
                schemas[pid] = result
                print(f"    p{pid} [discursive]: {len(result.get('key_theses', []))} theses — {result.get('elapsed_s', '?')}s")

        print(f"  Discursive extraction done: {time.time() - t0:.1f}s")

    with open(f"{output_dir}/03_schemas.json", "w") as f:
        json.dump(schemas, f, ensure_ascii=False, indent=2)

    # ═══════════════════════════════════════════════════════════
    # УРОВЕНЬ 3: Онтологический маппинг (Cloud)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("УРОВЕНЬ 3: Онтологический маппинг (Cloud)")
    print("=" * 60)

    # Подготавливаем схемы для онтологии (только не-empty)
    ont_input = {}
    page_contexts = {}
    for pid, schema in schemas.items():
        if schema.get("empty"):
            continue
        ont_input[pid] = schema
        page_contexts[pid] = json.dumps(schema, ensure_ascii=False)[:500]

    ontologies = ontology_map_all(ont_input, page_contexts, max_workers=MAX_WORKERS)

    # Индексируем по page_id
    ont_by_page = {o["page_id"]: o for o in ontologies}

    with open(f"{output_dir}/04_ontologies.json", "w") as f:
        json.dump(ontologies, f, ensure_ascii=False, indent=2)

    # ═══════════════════════════════════════════════════════════
    # УРОВЕНЬ 4: Прагматическая рефлексия (Cloud)
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("УРОВЕНЬ 4: Прагматическая рефлексия (Cloud)")
    print("=" * 60)

    reflect_input = {
        pid: ont for pid, ont in ont_by_page.items()
        if not ont.get("model", "").startswith("api_error") and not ont.get("model") == "parse_failed"
    }

    reflections = reflector_reflect_all(reflect_input, max_workers=MAX_WORKERS)

    with open(f"{output_dir}/05_reflections.json", "w") as f:
        json.dump(reflections, f, ensure_ascii=False, indent=2)

    doc.close()

    # ═══════════════════════════════════════════════════════════
    # ИТОГИ
    # ═══════════════════════════════════════════════════════════
    total_elapsed = time.time() - t_total

    # Собираем C-level рекомендации
    high_urgency = [r for r in reflections if r.get("urgency") == "HIGH"]
    medium_urgency = [r for r in reflections if r.get("urgency") == "MEDIUM"]

    summary = {
        "pdf_path": pdf_path,
        "total_pages": total_pages,
        "total_elapsed_s": round(total_elapsed, 1),
        "pipeline": "cloud-dashscope",
        "form_distribution": classification["stats"]["form_distribution"],
        "mixed_pages_decomposed": len(mixed_decompositions),
        "schemas_extracted": len(schemas),
        "ontologies_mapped": len(ontologies),
        "reflections": len(reflections),
        "high_urgency_count": len(high_urgency),
        "medium_urgency_count": len(medium_urgency),
        "recommendations": [
            {
                "page": r["page_id"],
                "action": r.get("recommended_action", ""),
                "urgency": r.get("urgency", "LOW"),
                "confidence": r.get("confidence", "LOW"),
                "significance": r.get("strategic_significance", "")[:200],
            }
            for r in sorted(reflections, key=lambda r: (
                0 if r.get("urgency") == "HIGH" else 1 if r.get("urgency") == "MEDIUM" else 2,
                r["page_id"],
            ))
        ],
    }

    with open(f"{output_dir}/06_summary.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("ПОЛНЫЙ ПАЙПЛАЙН ЗАВЕРШЁН")
    print("=" * 60)
    print(f"  Всего страниц: {total_pages}")
    print(f"  Общее время: {total_elapsed:.1f}s ({total_elapsed/total_pages:.1f}s/стр)")
    print(f"  HIGH urgency: {len(high_urgency)}")
    print(f"  MEDIUM urgency: {len(medium_urgency)}")
    print(f"  Результаты: {output_dir}/")

    # Топ-10 рекомендаций
    print(f"\n  Топ C-level рекомендаций:")
    for i, r in enumerate(summary["recommendations"][:10]):
        urgency_icon = "🔴" if r["urgency"] == "HIGH" else "🟡" if r["urgency"] == "MEDIUM" else "🟢"
        print(f"    {urgency_icon} p{r['page']}: {r['action'][:100]}")

    return summary


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python3 scripts/run_cloud_pipeline.py <путь к PDF> [output_dir]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(pdf_path):
        print(f"Файл не найден: {pdf_path}")
        sys.exit(1)

    run_full_pipeline(pdf_path, output_dir)