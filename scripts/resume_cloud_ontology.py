#!/usr/bin/env python3
"""Дозапуск: Уровень 3+4 через Cloud (DashScope) с ограниченной параллельностью.

Отличается от cloud_ontology.py:
- MAX_WORKERS=3 (избегаем rate-limit)
- Retry при ошибках (до 3 попыток)
- Таймаут 60s на запрос

Запуск:
  python3 scripts/resume_cloud_ontology.py output/run_2026-07-15_1107/
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import DASHSCOPE_KEY, DASHSCOPE_BASE

MAX_WORKERS = 3
RETRIES = 3
TEXT_MODEL = "qwen3.7-plus"

ONTOLOGY_PROMPT = """[РОЛЬ] Онтологический маппер
[ПРЕДМЕТ] Схема, извлечённая со страницы документа
[ЗАДАЧА] Привяжи элементы схемы к предметной онтологии
[ПРАВИЛА]
1. Для каждого элемента схемы определи его онтологический тип
2. Для каждой связи определи тип отношения
3. Синтезируй онтологическую модель: кто, на что, через что, с каким результатом
[ОГРАНИЧЕНИЕ] Не выдумывай данные. Только то, что есть в схеме.

Формат: JSON
{
  "entities": [{"name": "string", "type": "string", "role": "string"}],
  "relations": [{"from": "string", "to": "string", "type": "string"}],
  "model": "string"
}"""

REFLECTOR_PROMPT = """[РОЛЬ] Прагматический рефлектор
[ПРЕДМЕТ] Онтологическая модель страницы документа
[ЗАДАЧА] Синтезируй вывод для C-level руководителя
[ПРАВИЛА]
1. Оцени СТРАТЕГИЧЕСКУЮ ЗНАЧИМОСТЬ
2. Выдели КЛЮЧЕВЫЕ РИСКИ
3. Выдели ВОЗМОЖНОСТИ
4. Дай RECOMMENDED ACTION — одно конкретное действие
5. Оцени УВЕРЕННОСТЬ: HIGH/MEDIUM/LOW
[ОГРАНИЧЕНИЕ] Не выдумывай. Только на основе онтологической модели.

Формат: JSON
{
  "strategic_significance": "string",
  "risks": ["string"],
  "opportunities": ["string"],
  "recommended_action": "string",
  "confidence": "HIGH|MEDIUM|LOW",
  "urgency": "HIGH|MEDIUM|LOW"
}"""


def _call_dashscope(prompt: str, api_key: str, max_tokens: int = 1024) -> str:
    """Вызов DashScope с retry."""
    data = json.dumps({
        "model": TEXT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }).encode()

    last_error = None
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
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.loads(resp.read())
                return raw["choices"][0]["message"]["content"]
        except Exception as e:
            last_error = str(e)
            if attempt < RETRIES - 1:
                time.sleep(2 ** attempt)  # exponential backoff

    raise RuntimeError(f"DashScope failed after {RETRIES} attempts: {last_error}")


def _parse_json(text: str) -> dict:
    """Парсит JSON из текста."""
    try:
        j1, j2 = text.find("{"), text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass
    return {}


def _process_one(pid: int, schema: dict, domain_context: str, api_key: str) -> dict:
    """Обрабатывает одну страницу: ontology → reflector."""
    t0 = time.time()

    schema_str = json.dumps(schema, ensure_ascii=False)
    # Обрезаем схему до разумного размера
    if len(schema_str) > 2500:
        schema_str = schema_str[:2500]

    # Онтология
    ont_prompt = f"{ONTOLOGY_PROMPT}\n\n## СХЕМА\n{schema_str}\n\n## КОНТЕКСТ\n{domain_context[:300]}"

    try:
        ont_text = _call_dashscope(ont_prompt, api_key, max_tokens=1024)
        ontology = _parse_json(ont_text)
        if not ontology:
            ontology = {"entities": [], "relations": [], "model": "parse_failed"}
    except Exception as e:
        ontology = {"entities": [], "relations": [], "model": f"error: {e}"}

    t_ont = time.time() - t0

    # Рефлексия
    if ontology.get("entities") or ontology.get("model", "").startswith("error"):
        ont_str = json.dumps(ontology, ensure_ascii=False)[:2500]
        refl_prompt = f"{REFLECTOR_PROMPT}\n\n## ОНТОЛОГИЯ\n{ont_str}\n\n## КОНТЕКСТ\n{domain_context[:300]}"

        try:
            refl_text = _call_dashscope(refl_prompt, api_key, max_tokens=1024)
            reflection = _parse_json(refl_text)
            if not reflection:
                reflection = {"strategic_significance": "", "risks": [], "opportunities": [],
                              "recommended_action": "", "confidence": "LOW", "urgency": "LOW"}
        except Exception as e:
            reflection = {"strategic_significance": "", "risks": [], "opportunities": [],
                          "recommended_action": "", "confidence": "LOW", "urgency": "LOW"}
    else:
        reflection = {"strategic_significance": "", "risks": [], "opportunities": [],
                      "recommended_action": "", "confidence": "LOW", "urgency": "LOW"}

    t_total = time.time() - t0
    return {
        "page_id": pid,
        "ontology": ontology,
        "reflection": reflection,
        "elapsed_s": round(t_total, 1),
        "t_ont_s": round(t_ont, 1),
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

    api_key = str(DASHSCOPE_KEY)
    print(f"Resume from: {run_dir} (Cloud DashScope, {MAX_WORKERS} workers, {RETRIES} retries)")

    # Загружаем схемы
    schemas_path = f"{run_dir}/03_schemas.json"
    with open(schemas_path) as f:
        schemas_raw = json.load(f)

    if isinstance(schemas_raw, dict):
        schemas = {int(k): v for k, v in schemas_raw.items()}
    else:
        schemas = {s["page_id"]: s for s in schemas_raw}

    # Загружаем классификацию
    classification_path = f"{run_dir}/01_semiotic_classification.json"
    domain_context = ""
    if os.path.exists(classification_path):
        with open(classification_path) as f:
            classification = json.load(f)
        dist = classification.get("stats", {}).get("form_distribution", {})
        domain_context = f"Document: 81 pages. Forms: {dist}"

    # Фильтруем empty
    tasks = {pid: s for pid, s in schemas.items() if not s.get("empty")}
    total = len(tasks)
    print(f"Страниц для обработки: {total}")

    print("\n" + "=" * 60)
    print("УРОВЕНЬ 3+4: Онтология + Рефлексия (Cloud DashScope)")
    print("=" * 60)

    t_total = time.time()
    ontologies = {}
    reflections = {}
    completed = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_one, pid, schema, domain_context, api_key): pid
            for pid, schema in tasks.items()
        }
        for future in as_completed(futures):
            result = future.result()
            pid = result["page_id"]
            ontologies[pid] = result["ontology"]
            reflections[pid] = result["reflection"]
            completed += 1

            ont = result["ontology"]
            refl = result["reflection"]
            n_entities = len(ont.get("entities", []))
            n_relations = len(ont.get("relations", []))
            action = refl.get("recommended_action", "")[:80]
            urgency = refl.get("urgency", "?")

            if ont.get("model", "").startswith("error"):
                errors += 1

            print(
                f"  [{completed}/{total}] p{pid}: "
                f"{n_entities}e/{n_relations}r "
                f"[{urgency}] {action} "
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
        "errors": errors,
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
    print(f"ЗАВЕРШЕНО: {total_elapsed:.1f}s ({total_elapsed/total:.1f}s/стр)")
    print(f"  HIGH urgency: {len(high_urgency)}")
    print(f"  MEDIUM urgency: {len(medium_urgency)}")
    print(f"  Errors: {errors}")
    print(f"  Результаты: {run_dir}/")

    print(f"\n  Топ-10 C-level рекомендаций:")
    for i, r in enumerate(summary["recommendations"][:10]):
        icon = "🔴" if r["urgency"] == "HIGH" else "🟡" if r["urgency"] == "MEDIUM" else "🟢"
        print(f"    {icon} p{r['page']}: {r['action'][:100]}")


if __name__ == "__main__":
    main()