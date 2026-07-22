"""Шаг 3: Per-page Ontology & Reflection Generator.

Генерирует:
- 04_ontologies.json — онтология для каждой страницы (entities, relations, model)
- 05_reflections.json — рефлексия для каждой страницы (C-level вывод)

Использует локальную Ollama (qwen3.6:35b) в батчевом режиме (5 стр. за запрос).
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"
BATCH_SIZE = 1

BATCH_PROMPT = """[РОЛЬ] Онтолог + Рефлектор
[ПРЕДМЕТ] Пакет из {batch_size} схем страниц документа
[ЗАДАЧА] Для КАЖДОЙ страницы:
1. Построй онтологию: entities (имя, тип, роль), relations (from, to, type), model (краткая модель)
2. Синтезируй C-level рефлексию: strategic_significance, risks, opportunities, recommended_action, urgency, confidence
[ПРАВИЛА]
- Не выдумывай. Только на основе схемы
- Для каждой страницы — отдельный блок с page_id
- Если схема пустая/неинформативная — укажи confidence: LOW
[ОГРАНИЧЕНИЕ] Строгий JSON.

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

## СХЕМЫ
{schemas_json}"""


def _call_ollama(prompt: str, max_tokens: int = 4096) -> str:
    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.1, "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat", data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["message"]["content"]


def _parse_json(text: str) -> dict:
    try:
        j1, j2 = text.find("{"), text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass
    return {}


def _trim_schema(schema: dict) -> dict:
    """Обрезает схему до ключевых полей."""
    return {
        "form": schema.get("form", "?"),
        "page_title": str(schema.get("page_title", schema.get("title", "")))[:200],
        "conclusion": str(schema.get("conclusion", ""))[:200],
        "key_theses": schema.get("key_theses", [])[:3],
        "sets": [{"name": s.get("name", ""), "elements": s.get("elements", [])[:3]} for s in schema.get("sets", [])[:2]],
        "items": schema.get("items", [])[:5],
        "columns": schema.get("columns", [])[:5],
        "rows": [{"label": r.get("label", ""), "cells": r.get("cells", [])[:3]} for r in schema.get("rows", [])[:3]],
        "levels": [{"label": l.get("label", ""), "meaning": str(l.get("meaning", ""))[:100]} for l in schema.get("levels", [])[:3]],
        "zones": [{"form": z.get("form", "?"), "description": str(z.get("description", ""))[:100]} for z in schema.get("zones", [])[:3]] if schema.get("zones") else None,
        "zone_schemas": {
            zf: {
                "form": zf,
                "page_title": str(zs.get("page_title", ""))[:200],
                "conclusion": str(zs.get("conclusion", ""))[:200],
                "items": zs.get("items", [])[:3],
                "sets": [{"name": s.get("name", ""), "elements": s.get("elements", [])[:3]} for s in zs.get("sets", [])[:2]],
            }
            for zf, zs in schema.get("zone_schemas", {}).items()
            if isinstance(zs, dict)
        } if schema.get("zone_schemas") else None,
        "key_terms": schema.get("key_terms", [])[:5],
        "all_metrics": schema.get("all_metrics", [])[:5],
        "full_text": str(schema.get("full_text", ""))[:400],
    }


def generate_ontology_reflection(run_dir: str) -> tuple[list[dict], list[dict]]:
    """Генерирует 04_ontologies.json и 05_reflections.json."""
    schemas_path = f"{run_dir}/03_schemas.json"
    if not Path(schemas_path).exists():
        print(f"  Схемы не найдены: {schemas_path}")
        return [], []

    with open(schemas_path) as f:
        schemas_raw = json.load(f)

    if isinstance(schemas_raw, dict):
        schemas = {int(k): v for k, v in schemas_raw.items()}
    else:
        schemas = {s["page_id"]: s for s in schemas_raw}

    # Фильтруем empty
    tasks = [(pid, s) for pid, s in schemas.items() if not s.get("empty")]
    tasks.sort(key=lambda x: x[0])

    batches = [tasks[i:i + BATCH_SIZE] for i in range(0, len(tasks), BATCH_SIZE)]
    total_batches = len(batches)

    print(f"  Ontology+Reflection: {len(tasks)} pages, {total_batches} batches")

    all_ontologies = []
    all_reflections = []
    t_total = time.time()

    for i, batch in enumerate(batches):
        trimmed = [
            {"page_id": pid, "schema": _trim_schema(schema)}
            for pid, schema in batch
        ]
        schemas_json = json.dumps(trimmed, ensure_ascii=False)
        if len(schemas_json) > 6000:
            schemas_json = schemas_json[:6000]

        prompt = BATCH_PROMPT.format(batch_size=len(batch), schemas_json=schemas_json)
        result = _parse_json(_call_ollama(prompt, max_tokens=4096))

        pages = result.get("pages", [])
        for p in pages:
            if not isinstance(p, dict):
                continue
            if "page_id" not in p:
                continue
            try:
                all_ontologies.append({"page_id": p["page_id"], **(p.get("ontology", {}))})
                all_reflections.append({"page_id": p["page_id"], **(p.get("reflection", {}))})
            except (TypeError, AttributeError):
                continue

        n_entities = sum(len(p.get("ontology", {}).get("entities", [])) for p in pages if isinstance(p, dict))
        high = sum(1 for p in pages if isinstance(p, dict) and p.get("reflection", {}).get("urgency") == "HIGH")
        print(f"  Batch {i+1}/{total_batches}: {len(pages)} pages, {n_entities} entities, {high} HIGH")

    all_ontologies.sort(key=lambda o: o["page_id"])
    all_reflections.sort(key=lambda r: r["page_id"])

    total_elapsed = time.time() - t_total
    print(f"  Ontology+Reflection done: {total_elapsed:.1f}s")

    with open(f"{run_dir}/04_ontologies.json", "w") as f:
        json.dump(all_ontologies, f, ensure_ascii=False, indent=2)
    with open(f"{run_dir}/05_reflections.json", "w") as f:
        json.dump(all_reflections, f, ensure_ascii=False, indent=2)

    print(f"  Saved: {run_dir}/04_ontologies.json, {run_dir}/05_reflections.json")
    return all_ontologies, all_reflections


if __name__ == "__main__":
    import sys
    run_dir = sys.argv[1] if len(sys.argv) > 1 else "output/run_2026-07-15_1107"
    generate_ontology_reflection(run_dir)