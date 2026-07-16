#!/usr/bin/env python3
"""Генерация C-level рекомендаций из схем — один запрос на все 80 страниц.

Отправляет все схемы в одном запросе к qwen3.6:35b, просит дать топ-рекомендации.
Быстрее, чем батчи по 5 страниц.

Запуск:
  python3 scripts/generate_recommendations.py output/run_2026-07-15_1107/
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"


def _trim_schema(schema: dict) -> dict:
    """Безопасно обрезает схему до ключевых полей."""
    return {
        "form": schema.get("form", "?"),
        "page_title": str(schema.get("page_title", schema.get("title", "")))[:200],
        "conclusion": str(schema.get("conclusion", ""))[:200],
        "key_theses": schema.get("key_theses", [])[:3],
        "sets": [{"name": s.get("name", ""), "elements": s.get("elements", [])[:3]} for s in schema.get("sets", [])[:2]],
        "levels": [{"label": l.get("label", ""), "meaning": str(l.get("meaning", ""))[:100]} for l in schema.get("levels", [])[:3]],
        "items": schema.get("items", [])[:5],
        "columns": schema.get("columns", [])[:5],
        "rows": [{"label": r.get("label", ""), "cells": r.get("cells", [])[:3]} for r in schema.get("rows", [])[:3]],
        "zones": [
            {"form": z.get("form", "?"), "description": str(z.get("description", ""))[:100]}
            for z in schema.get("zones", [])[:3]
        ] if schema.get("zones") else None,
        "key_terms": schema.get("key_terms", [])[:5],
        "all_metrics": schema.get("all_metrics", [])[:5],
        "regions": [{"name": r.get("name", ""), "metrics": r.get("metrics", {})} for r in schema.get("regions", [])[:3]],
        "curves": [{"name": c.get("name", ""), "direction": c.get("direction", "")} for c in schema.get("curves", [])[:2]],
        "full_text": str(schema.get("full_text", ""))[:400],
    }


PROMPT = """[РОЛЬ] C-level аналитик
[ПРЕДМЕТ] Вычислительный граф 80-страничного документа «Стратегия ИАфр РАН»
[ЗАДАЧА] На основе ВСЕХ схем страниц сгенерируй сводку для C-level руководителя
[ПРАВИЛА]
1. Выдели 15-20 КЛЮЧЕВЫХ РЕКОМЕНДАЦИЙ (HIGH urgency) — конкретные действия
2. Выдели 5-10 СТРАТЕГИЧЕСКИХ РИСКОВ
3. Выдели 5-10 СТРАТЕГИЧЕСКИХ ВОЗМОЖНОСТЕЙ
4. Для КАЖДОЙ страницы дай краткую C-level аннотацию (1 предложение)
5. Оцени общую уверенность: HIGH/MEDIUM/LOW
[ОГРАНИЧЕНИЕ] Не выдумывай. Только на основе предоставленных схем.
Вывод — для российского C-level руководителя (государство + бизнес).

Формат: JSON
{
  "top_recommendations": [
    {"page": N, "action": "string", "urgency": "HIGH|MEDIUM|LOW", "rationale": "string"}
  ],
  "strategic_risks": ["string", ...],
  "strategic_opportunities": ["string", ...],
  "page_annotations": [
    {"page": N, "annotation": "string", "urgency": "HIGH|MEDIUM|LOW"}
  ],
  "overall_confidence": "HIGH|MEDIUM|LOW",
  "executive_summary": "string — 3-5 предложений для C-level"
}

## СХЕМЫ ВСЕХ СТРАНИЦ
{schemas_json}"""


def main():
    if len(sys.argv) < 2:
        runs = sorted(Path("output").glob("run_*"))
        if not runs:
            print("Нет run-директорий")
            sys.exit(1)
        run_dir = str(runs[-1])
    else:
        run_dir = sys.argv[1]

    print(f"Generate recommendations from: {run_dir}")

    # Загружаем схемы
    with open(f"{run_dir}/03_schemas.json") as f:
        schemas_raw = json.load(f)

    if isinstance(schemas_raw, dict):
        schemas = {int(k): v for k, v in schemas_raw.items()}
    else:
        schemas = {s["page_id"]: s for s in schemas_raw}

    # Триммим и собираем
    trimmed = []
    for pid in sorted(schemas.keys()):
        if schemas[pid].get("empty"):
            continue
        trimmed.append({"page_id": pid, "schema": _trim_schema(schemas[pid])})

    schemas_json = json.dumps(trimmed, ensure_ascii=False)
    # Ограничиваем до 30K символов
    if len(schemas_json) > 30000:
        # Урезаем ещё сильнее
        for t in trimmed:
            t["schema"] = {k: v for k, v in t["schema"].items() if v not in (None, [], "", {})}
        schemas_json = json.dumps(trimmed, ensure_ascii=False)[:30000]

    print(f"  Схем: {len(trimmed)}, размер JSON: {len(schemas_json)} chars")

    prompt = PROMPT.replace("{schemas_json}", schemas_json)
    print(f"  Размер промпта: {len(prompt)} chars")

    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0.1,
        "stream": False,
    }).encode()

    print("  Отправка запроса к Ollama...")
    t0 = time.time()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_LOCAL_BASE}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = json.loads(resp.read())
            result_text = raw["message"]["content"]
    except Exception as e:
        print(f"  Ошибка: {e}")
        sys.exit(1)

    elapsed = time.time() - t0
    print(f"  Ответ получен за {elapsed:.1f}s")

    # Парсим
    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            result = json.loads(result_text[j1:j2])
        else:
            print("  JSON не найден в ответе")
            result = {"executive_summary": result_text[:500]}
    except json.JSONDecodeError:
        print("  Ошибка парсинга JSON")
        result = {"executive_summary": result_text[:500]}

    # Сохраняем
    out_path = f"{run_dir}/07_recommendations.json"
    with open(out_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  Сохранено: {out_path}")

    # Выводим ключевое
    recs = result.get("top_recommendations", [])
    print(f"\n  Топ рекомендаций ({len(recs)}):")
    for i, r in enumerate(recs[:15]):
        icon = "🔴" if r.get("urgency") == "HIGH" else "🟡" if r.get("urgency") == "MEDIUM" else "🟢"
        print(f"    {icon} p{r.get('page', '?')}: {r.get('action', '')[:100]}")

    summary = result.get("executive_summary", "")
    if summary:
        print(f"\n  Executive Summary:\n    {summary[:500]}")

    # Обновляем summary.json
    try:
        with open(f"{run_dir}/06_summary.json") as f:
            summary_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        summary_data = {}

    summary_data["recommendations"] = recs
    summary_data["executive_summary"] = result.get("executive_summary", "")
    summary_data["strategic_risks"] = result.get("strategic_risks", [])
    summary_data["strategic_opportunities"] = result.get("strategic_opportunities", [])
    summary_data["page_annotations"] = result.get("page_annotations", [])

    with open(f"{run_dir}/06_summary.json", "w") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    print(f"  Summary обновлён: {run_dir}/06_summary.json")


if __name__ == "__main__":
    main()