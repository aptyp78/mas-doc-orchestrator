#!/usr/bin/env python3
"""Дозапуск: Уровень 3 (Онтология) + Уровень 4 (Рефлексия) через локальную Ollama.

В отличие от Cloud-версии, локальная Ollama не имеет rate-limit'ов
и надёжно обрабатывает все страницы, хоть и медленнее (50s/стр).

Запуск:
  python3 scripts/resume_ontology_reflector_local.py output/run_2026-07-15_1107/
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.semiotic.ontology import map_to_ontology
from src.semiotic.reflector import reflect

MAX_WORKERS = 4  # 4 параллельных запроса к локальной Ollama


def _process_one(pid: int, schema: dict, domain_context: str) -> dict:
    """Обрабатывает одну страницу: ontology → reflector."""
    t0 = time.time()
    page_context = json.dumps(schema, ensure_ascii=False)[:500]

    # Онтология
    ontology = map_to_ontology(schema, page_context)
    t_ont = time.time() - t0

    # Рефлексия
    if ontology.get("entities") or ontology.get("model") not in ("parse_failed", "", None):
        reflection = reflect(ontology, domain_context)
    else:
        reflection = {
            "strategic_significance": "", "risks": [], "opportunities": [],
            "recommended_action": "", "confidence": "LOW", "urgency": "LOW",
        }

    t_total = time.time() - t0
    n_entities = len(ontology.get("entities", []))
    n_relations = len(ontology.get("relations", []))
    action = reflection.get("recommended_action", "")[:80]
    urgency = reflection.get("urgency", "?")

    return {
        "page_id": pid,
        "ontology": ontology,
        "reflection": reflection,
        "elapsed_s": round(t_total, 1),
        "n_entities": n_entities,
        "n_relations": n_relations,
        "action_preview": action,
        "urgency": urgency,
    }


def main():
    if len(sys.argv) < 2:
        runs = sorted(Path("output").glob("run_*"))
        if not runs:
            print("Нет run-директорий")
            sys.exit(1)
        run_dir = str(runs[-1])
    else:
        run_dir = sys.argv[1]

    print(f"Resume from: {run_dir} (local Ollama, {MAX_WORKERS} workers)")

    # Загружаем схемы
    schemas_path = f"{run_dir}/03_schemas.json"
    with open(schemas_path) as f:
        schemas_raw = json.load(f)

    if isinstance(schemas_raw, dict):
        schemas = {int(k): v for k, v in schemas_raw.items()}
    else:
        schemas = {s["page_id"]: s for s in schemas_raw}

    print(f"Загружено схем: {len(schemas)}")

    # Загружаем классификацию
    classification_path = f"{run_dir}/01_semiotic_classification.json"
    domain_context = ""
    if os.path.exists(classification_path):
        with open(classification_path) as f:
            classification = json.load(f)
        dist = classification.get("stats", {}).get("form_distribution", {})
        domain_context = f"Document: 81 pages. Forms: {dist}"

    # Фильтруем empty
    tasks = {
        pid: schema for pid, schema in schemas.items()
        if not schema.get("empty")
    }
    print(f"Страниц для обработки: {len(tasks)}")

    # ================================================================
    # Параллельная обработка: ontology → reflector
    # ================================================================
    print("\n" + "=" * 60)
    print("УРОВЕНЬ 3+4: Онтология + Рефлексия (локальная Ollama)")
    print("=" * 60)

    t_total = time.time()
    ontologies = {}
    reflections = {}
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_one, pid, schema, domain_context): pid
            for pid, schema in tasks.items()
        }
        for future in as_completed(futures):
            result = future.result()
            pid = result["page_id"]
            ontologies[pid] = result["ontology"]
            reflections[pid] = result["reflection"]
            completed += 1
            print(
                f"  [{completed}/{len(tasks)}] p{pid}: "
                f"{result['n_entities']}e/{result['n_relations']}r "
                f"[{result['urgency']}] {result['action_preview']} "
                f"— {result['elapsed_s']}s"
            )

    total_elapsed = time.time() - t_total

    # Сохраняем
    ont_list = [{"page_id": pid, **ont} for pid, ont in ontologies.items()]
    ont_list.sort(key=lambda o: o["page_id"])
    with open(f"{run_dir}/04_ontologies.json", "w") as f:
        json.dump(ont_list, f, ensure_ascii=False, indent=2)

    refl_list = [{"page_id": pid, **refl} for pid, refl in reflections.items()]
    refl_list.sort(key=lambda r: r["page_id"])
    with open(f"{run_dir}/05_reflections.json", "w") as f:
        json.dump(refl_list, f, ensure_ascii=False, indent=2)

    # Итоги
    high_urgency = [r for r in refl_list if r.get("urgency") == "HIGH"]
    medium_urgency = [r for r in refl_list if r.get("urgency") == "MEDIUM"]

    summary = {
        "total_pages": len(schemas),
        "ontologies_mapped": len(ontologies),
        "reflections": len(reflections),
        "high_urgency_count": len(high_urgency),
        "medium_urgency_count": len(medium_urgency),
        "total_elapsed_s": round(total_elapsed, 1),
        "recommendations": [
            {
                "page": r["page_id"],
                "action": r.get("recommended_action", ""),
                "urgency": r.get("urgency", "LOW"),
                "confidence": r.get("confidence", "LOW"),
                "significance": r.get("strategic_significance", "")[:200],
            }
            for r in sorted(refl_list, key=lambda r: (
                0 if r.get("urgency") == "HIGH" else 1 if r.get("urgency") == "MEDIUM" else 2,
                r["page_id"],
            ))
        ],
    }

    with open(f"{run_dir}/06_summary.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"ЗАВЕРШЕНО: {total_elapsed:.1f}s ({total_elapsed/len(tasks):.1f}s/стр)")
    print(f"  HIGH urgency: {len(high_urgency)}")
    print(f"  MEDIUM urgency: {len(medium_urgency)}")
    print(f"  Результаты: {run_dir}/")

    print(f"\n  Топ-10 C-level рекомендаций:")
    for i, r in enumerate(summary["recommendations"][:10]):
        icon = "🔴" if r["urgency"] == "HIGH" else "🟡" if r["urgency"] == "MEDIUM" else "🟢"
        print(f"    {icon} p{r['page']}: {r['action'][:100]}")


if __name__ == "__main__":
    main()