#!/usr/bin/env python3
"""Дозапуск: Уровень 3 (Онтология) + Уровень 4 (Рефлексия) из сохранённых схем.

Запуск:
  python3 scripts/resume_ontology_reflector.py output/run_2026-07-15_1107/
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.semiotic.cloud_ontology import map_all as ontology_map_all
from src.semiotic.cloud_reflector import reflect_all as reflector_reflect_all


def main():
    if len(sys.argv) < 2:
        # Найти последний run
        runs = sorted(Path("output").glob("run_*"))
        if not runs:
            print("Нет run-директорий")
            sys.exit(1)
        run_dir = str(runs[-1])
    else:
        run_dir = sys.argv[1]

    print(f"Resume from: {run_dir}")

    # Загружаем схемы
    schemas_path = f"{run_dir}/03_schemas.json"
    if not os.path.exists(schemas_path):
        print(f"Файл схем не найден: {schemas_path}")
        sys.exit(1)

    with open(schemas_path) as f:
        schemas_raw = json.load(f)

    # Преобразуем в словарь {page_id: schema}
    if isinstance(schemas_raw, dict):
        schemas = {int(k): v for k, v in schemas_raw.items()}
    elif isinstance(schemas_raw, list):
        schemas = {s["page_id"]: s for s in schemas_raw}
    else:
        print(f"Неизвестный формат схем: {type(schemas_raw)}")
        sys.exit(1)

    print(f"Загружено схем: {len(schemas)}")

    # Загружаем классификацию для статистики
    classification_path = f"{run_dir}/01_semiotic_classification.json"
    domain_context = ""
    if os.path.exists(classification_path):
        with open(classification_path) as f:
            classification = json.load(f)
        dist = classification.get("stats", {}).get("form_distribution", {})
        domain_context = f"Document: 81 pages. Forms: {dist}"

    # ================================================================
    # УРОВЕНЬ 3: Онтологический маппинг (Cloud)
    # ================================================================
    print("\n" + "=" * 60)
    print("УРОВЕНЬ 3: Онтологический маппинг (Cloud)")
    print("=" * 60)

    # Filter out empty pages
    ont_input = {}
    page_contexts = {}
    for pid, schema in schemas.items():
        if schema.get("empty"):
            continue
        ont_input[pid] = schema
        page_contexts[pid] = json.dumps(schema, ensure_ascii=False)[:500]

    print(f"  Страниц для онтологии: {len(ont_input)}")

    ontologies = ontology_map_all(ont_input, page_contexts, max_workers=8)
    ont_by_page = {o["page_id"]: o for o in ontologies}

    with open(f"{run_dir}/04_ontologies.json", "w") as f:
        json.dump(ontologies, f, ensure_ascii=False, indent=2)

    # ================================================================
    # УРОВЕНЬ 4: Прагматическая рефлексия (Cloud)
    # ================================================================
    print("\n" + "=" * 60)
    print("УРОВЕНЬ 4: Прагматическая рефлексия (Cloud)")
    print("=" * 60)

    reflect_input = {
        pid: ont for pid, ont in ont_by_page.items()
        if not ont.get("model", "").startswith("api_error") and not ont.get("model") == "parse_failed"
    }

    print(f"  Страниц для рефлексии: {len(reflect_input)}")

    reflections = reflector_reflect_all(reflect_input, domain_context=domain_context, max_workers=8)

    with open(f"{run_dir}/05_reflections.json", "w") as f:
        json.dump(reflections, f, ensure_ascii=False, indent=2)

    # ================================================================
    # ИТОГИ
    # ================================================================
    high_urgency = [r for r in reflections if r.get("urgency") == "HIGH"]
    medium_urgency = [r for r in reflections if r.get("urgency") == "MEDIUM"]

    summary = {
        "total_pages": len(schemas),
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

    with open(f"{run_dir}/06_summary.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("ОНТОЛОГИЯ + РЕФЛЕКСИЯ ЗАВЕРШЕНЫ")
    print("=" * 60)
    print(f"  HIGH urgency: {len(high_urgency)}")
    print(f"  MEDIUM urgency: {len(medium_urgency)}")
    print(f"  LOW/other: {len(reflections) - len(high_urgency) - len(medium_urgency)}")

    print(f"\n  Топ-10 C-level рекомендаций:")
    for i, r in enumerate(summary["recommendations"][:10]):
        urgency_icon = "🔴" if r["urgency"] == "HIGH" else "🟡" if r["urgency"] == "MEDIUM" else "🟢"
        print(f"    {urgency_icon} p{r['page']}: {r['action'][:100]}")

    print(f"\n  Результаты: {run_dir}/")


if __name__ == "__main__":
    main()