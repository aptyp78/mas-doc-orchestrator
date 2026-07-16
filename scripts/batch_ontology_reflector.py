#!/usr/bin/env python3
"""Батчевая онтология + рефлексия: 10 страниц за один API-запрос.

Отправляет Cloud API (DashScope qwen3.7-plus) пакет из 10 страниц,
получает онтологию и C-level рекомендацию для каждой страницы в одном ответе.

8 батчей × ~20s = ~160s на все 80 страниц.

Запуск:
  python3 scripts/batch_ontology_reflector.py output/run_2026-07-15_1107/
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import DASHSCOPE_KEY, DASHSCOPE_BASE

TEXT_MODEL = "qwen3.7-plus"
BATCH_SIZE = 10
RETRIES = 2

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


def _process_batch(batch: list[tuple[int, dict]], api_key: str, batch_num: int, total_batches: int) -> list[dict]:
    """Обрабатывает батч страниц за один запрос."""
    t0 = time.time()

    schemas_json = json.dumps(
        [{"page_id": pid, "schema": schema} for pid, schema in batch],
        ensure_ascii=False,
    )

    # Ограничиваем размер
    if len(schemas_json) > 15000:
        trimmed = []
        for pid, schema in batch:
            s = json.dumps(schema, ensure_ascii=False)
            if len(s) > 800:
                # Безопасное усечение: берём только ключевые поля
                trimmed.append({
                    "page_id": pid,
                    "schema": {
                        "form": schema.get("form", "?"),
                        "page_title": str(schema.get("page_title", schema.get("title", "")))[:200],
                        "conclusion": str(schema.get("conclusion", ""))[:200],
                        "key_theses": schema.get("key_theses", [])[:3],
                        "sets": schema.get("sets", [])[:2],
                        "levels": schema.get("levels", [])[:2],
                        "zones": schema.get("zones", [])[:2],
                        "_truncated": True,
                    },
                })
            else:
                trimmed.append({"page_id": pid, "schema": schema})
        schemas_json = json.dumps(trimmed, ensure_ascii=False)[:15000]

    prompt = BATCH_PROMPT.format(
        batch_size=len(batch),
        schemas_json=schemas_json,
    )

    data = json.dumps({
        "model": TEXT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0.1,
    }).encode()

    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(
                f"{DASHSCOPE_BASE}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = json.loads(resp.read())
                result_text = raw["choices"][0]["message"]["content"]

            # Парсим JSON
            try:
                j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
                if j1 >= 0 and j2 > j1:
                    parsed = json.loads(result_text[j1:j2])
                    pages = parsed.get("pages", [])
                    elapsed = time.time() - t0
                    print(f"  Batch {batch_num}/{total_batches}: {len(pages)} pages — {elapsed:.1f}s")
                    return pages
            except (json.JSONDecodeError, KeyError) as e:
                print(f"  Batch {batch_num}/{total_batches}: JSON parse error: {e}, retrying...")
                if attempt < RETRIES - 1:
                    time.sleep(3)
                continue

        except Exception as e:
            print(f"  Batch {batch_num}/{total_batches}: API error: {e}, retrying...")
            if attempt < RETRIES - 1:
                time.sleep(5)

    # Fallback: возвращаем пустые результаты
    elapsed = time.time() - t0
    print(f"  Batch {batch_num}/{total_batches}: FAILED after {RETRIES} retries — {elapsed:.1f}s")
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

    api_key = str(DASHSCOPE_KEY)
    print(f"Batch ontology+reflector: {run_dir}")

    # Загружаем схемы
    schemas_path = f"{run_dir}/03_schemas.json"
    with open(schemas_path) as f:
        schemas_raw = json.load(f)

    if isinstance(schemas_raw, dict):
        schemas = {int(k): v for k, v in schemas_raw.items()}
    else:
        schemas = {s["page_id"]: s for s in schemas_raw}

    # Фильтруем empty
    tasks = [(pid, s) for pid, s in schemas.items() if not s.get("empty")]
    tasks.sort(key=lambda x: x[0])

    # Разбиваем на батчи
    batches = [tasks[i:i + BATCH_SIZE] for i in range(0, len(tasks), BATCH_SIZE)]
    total_batches = len(batches)
    print(f"Страниц: {len(tasks)}, батчей: {total_batches} × {BATCH_SIZE}")

    print("\n" + "=" * 60)
    print("БАТЧЕВАЯ ОНТОЛОГИЯ + РЕФЛЕКСИЯ (Cloud DashScope)")
    print("=" * 60)

    t_total = time.time()
    all_pages = []

    for i, batch in enumerate(batches):
        pages = _process_batch(batch, api_key, i + 1, total_batches)
        all_pages.extend(pages)

    total_elapsed = time.time() - t_total

    # Разделяем на ontology и reflections
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

    # Итоги
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