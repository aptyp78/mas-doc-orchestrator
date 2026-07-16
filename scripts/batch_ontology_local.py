#!/usr/bin/env python3
"""Батчевая онтология + рефлексия через локальную Ollama.

5 страниц за один запрос к qwen3.6:35b.
16 батчей × ~90s = ~24 минуты на все 80 страниц.

Запуск:
  python3 scripts/batch_ontology_local.py output/run_2026-07-15_1107/
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"
BATCH_SIZE = 5

BATCH_PROMPT = """[РОЛЬ] Онтологический маппер + Прагматический рефлектор
[ПРЕДМЕТ] Пакет из {batch_size} схем страниц документа
[ЗАДАЧА] Для КАЖДОЙ страницы:
1. Привяжи элементы схемы к предметной онтологии (entities + relations)
2. Синтезируй C-level вывод: стратегическая значимость, риски, возможности, recommended action
[ПРАВИЛА]
- Для каждой страницы — отдельный блок с page_id
- Не выдумывай данные. Только то, что есть в схеме
- Рекомендации — для российского C-level руководителя
[ОГРАНИЧЕНИЕ] Результат — строгий JSON с массивом pages.

Формат: JSON
{{
  "pages": [
    {{
      "page_id": N,
      "ontology": {{
        "entities": [{{"name": "string", "type": "string", "role": "string"}}],
        "relations": [{{"from": "string", "to": "string", "type": "string"}}],
        "model": "string"
      }},
      "reflection": {{
        "strategic_significance": "string",
        "risks": ["string"],
        "opportunities": ["string"],
        "recommended_action": "string",
        "confidence": "HIGH|MEDIUM|LOW",
        "urgency": "HIGH|MEDIUM|LOW"
      }}
    }}
  ]
}}

## СХЕМЫ СТРАНИЦ
{schemas_json}"""


def _trim_schema(schema: dict) -> dict:
    """Безопасно обрезает схему до ключевых полей."""
    return {
        "form": schema.get("form", "?"),
        "page_title": str(schema.get("page_title", schema.get("title", "")))[:300],
        "conclusion": str(schema.get("conclusion", ""))[:300],
        "key_theses": schema.get("key_theses", [])[:3],
        "sets": schema.get("sets", [])[:2],
        "levels": schema.get("levels", [])[:2],
        "items": schema.get("items", [])[:5],
        "columns": schema.get("columns", [])[:5],
        "rows": schema.get("rows", [])[:3],
        "zones": [
            {"zone_id": z.get("zone_id", "?"), "form": z.get("form", "?"), "description": str(z.get("description", ""))[:100]}
            for z in schema.get("zones", [])[:3]
        ] if schema.get("zones") else None,
        "zone_schemas": schema.get("zone_schemas"),
        "overall_structure": str(schema.get("overall_structure", ""))[:200],
        "key_terms": schema.get("key_terms", [])[:5],
        "all_metrics": schema.get("all_metrics", [])[:5],
        "regions": schema.get("regions", [])[:3],
        "curves": schema.get("curves", [])[:2],
        "intersections": schema.get("intersections", [])[:2],
        "center": schema.get("center"),
        "element_count": schema.get("element_count"),
        "full_text": str(schema.get("full_text", ""))[:500],
    }


def _process_batch(batch: list[tuple[int, dict]], batch_num: int, total_batches: int) -> list[dict]:
    """Обрабатывает батч страниц через локальную Ollama."""
    t0 = time.time()

    # Триммим схемы
    trimmed = [{"page_id": pid, "schema": _trim_schema(schema)} for pid, schema in batch]
    schemas_json = json.dumps(trimmed, ensure_ascii=False)

    # Ограничиваем размер
    if len(schemas_json) > 8000:
        schemas_json = schemas_json[:8000]

    prompt = BATCH_PROMPT.format(batch_size=len(batch), schemas_json=schemas_json)

    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0.1,
        "stream": False,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_LOCAL_BASE}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = json.loads(resp.read())
            result_text = raw["message"]["content"]

        # Парсим JSON
        try:
            j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
            if j1 >= 0 and j2 > j1:
                parsed = json.loads(result_text[j1:j2])
                pages = parsed.get("pages", [])
                elapsed = time.time() - t0
                urgencies = [p.get("reflection", {}).get("urgency", "?") for p in pages]
                print(f"  Batch {batch_num}/{total_batches}: {len(pages)} pages {urgencies} — {elapsed:.1f}s")
                return pages
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Batch {batch_num}/{total_batches}: JSON parse error: {e}")

    except Exception as e:
        print(f"  Batch {batch_num}/{total_batches}: API error: {e}")

    # Fallback
    elapsed = time.time() - t0
    print(f"  Batch {batch_num}/{total_batches}: FAILED — {elapsed:.1f}s")
    return [
        {
            "page_id": pid,
            "ontology": {"entities": [], "relations": [], "model": "batch_failed"},
            "reflection": {
                "strategic_significance": "", "risks": [], "opportunities": [],
                "recommended_action": "", "confidence": "LOW", "urgency": "LOW",
            },
        }
        for pid, _ in batch
    ]


def main():
    if len(sys.argv) < 2:
        runs = sorted(Path("output").glob("run_*"))
        if not runs:
            print("Нет run-директорий")
            sys.exit(1)
        run_dir = str(runs[-1])
    else:
        run_dir = sys.argv[1]

    print(f"Batch ontology+reflector (local): {run_dir}")

    # Загружаем схемы
    schemas_path = f"{run_dir}/03_schemas.json"
    with open(schemas_path) as f:
        schemas_raw = json.load(f)

    if isinstance(schemas_raw, dict):
        schemas = {int(k): v for k, v in schemas_raw.items()}
    else:
        schemas = {s["page_id"]: s for s in schemas_raw}

    tasks = [(pid, s) for pid, s in schemas.items() if not s.get("empty")]
    tasks.sort(key=lambda x: x[0])

    batches = [tasks[i:i + BATCH_SIZE] for i in range(0, len(tasks), BATCH_SIZE)]
    total_batches = len(batches)
    print(f"Страниц: {len(tasks)}, батчей: {total_batches} × {BATCH_SIZE}")

    print("\n" + "=" * 60)
    print("БАТЧЕВАЯ ОНТОЛОГИЯ + РЕФЛЕКСИЯ (локальная Ollama)")
    print("=" * 60)

    t_total = time.time()
    all_pages = []

    for i, batch in enumerate(batches):
        pages = _process_batch(batch, i + 1, total_batches)
        all_pages.extend(pages)

    total_elapsed = time.time() - t_total

    ontologies = []
    reflections = []
    for p in all_pages:
        ontologies.append({"page_id": p["page_id"], **p.get("ontology", {})})
        reflections.append({"page_id": p["page_id"], **p.get("reflection", {})})

    ontologies.sort(key=lambda o: o["page_id"])
    reflections.sort(key=lambda r: r["page_id"])

    with open(f"{run_dir}/04_ontologies.json", "w") as f:
        json.dump(ontologies, f, ensure_ascii=False, indent=2)

    with open(f"{run_dir}/05_reflections.json", "w") as f:
        json.dump(reflections, f, ensure_ascii=False, indent=2)

    high_urgency = [r for r in reflections if r.get("urgency") == "HIGH"]
    medium_urgency = [r for r in reflections if r.get("urgency") == "MEDIUM"]

    summary = {
        "total_pages": len(schemas),
        "ontologies_mapped": len(ontologies),
        "reflections": len(reflections),
        "high_urgency_count": len(high_urgency),
        "medium_urgency_count": len(medium_urgency),
        "total_elapsed_s": round(total_elapsed, 1),
        "batches": total_batches,
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

    print(f"\n{'=' * 60}")
    print(f"ЗАВЕРШЕНО: {total_elapsed:.1f}s")
    print(f"  HIGH urgency: {len(high_urgency)}")
    print(f"  MEDIUM urgency: {len(medium_urgency)}")
    print(f"  Результаты: {run_dir}/")

    print(f"\n  Топ-10 C-level рекомендаций:")
    for i, r in enumerate(summary["recommendations"][:10]):
        icon = "🔴" if r["urgency"] == "HIGH" else "🟡" if r["urgency"] == "MEDIUM" else "🟢"
        print(f"    {icon} p{r['page']}: {r['action'][:100]}")


if __name__ == "__main__":
    main()