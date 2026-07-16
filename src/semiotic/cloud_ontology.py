"""Уровень 3: Онтологический маппер (Cloud — DashScope).

Использует qwen3.7-plus через DashScope для быстрого онтологического анализа.
~3-5 сек/страницу против 50 сек/страницу у локальной Ollama.
"""

from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.utils.config import DASHSCOPE_KEY, DASHSCOPE_BASE

MODEL = "qwen3.7-plus"
MAX_WORKERS = 8

ONTOLOGY_PROMPT = """[РОЛЬ] Онтологический маппер
[ПРЕДМЕТ] Схема, извлечённая со страницы документа
[ЗАДАЧА] Привяжи элементы схемы к предметной онтологии
[ПРАВИЛА]
1. Для каждого элемента схемы определи его онтологический тип:
   - Геополитический актор (государство, блок стран)
   - Критический минерал / Ресурс
   - Мера зависимости (%, доля, объём)
   - Стратегия / Политика
   - Инструмент контроля (логистика, переработка, финансы)
   - Регион / Страна-источник
2. Для каждой связи определи тип отношения:
   - КОНКУРИРУЕТ_ЗА
   - КОНТРОЛИРУЕТ
   - ЗАВИСИТ_ОТ
   - ИНВЕСТИРУЕТ_В
   - ДОМИНИРУЕТ_В
3. Синтезируй онтологическую модель: кто, на что, через что, с каким результатом
[ОГРАНИЧЕНИЕ] Не выдумывай данные. Только то, что есть в схеме.

Формат: JSON
{
  "entities": [
    {"name": "string", "type": "string", "role": "string", "evidence": "string"}
  ],
  "relations": [
    {"from": "string", "to": "string", "type": "string", "evidence": "string"}
  ],
  "model": "string — краткая онтологическая модель страницы"
}"""


def _map_one(page_id: int, schema: dict, page_context: str, api_key: str) -> dict:
    """Маппит одну страницу в онтологию через DashScope."""
    t0 = time.time()

    prompt = (
        f"{ONTOLOGY_PROMPT}\n\n"
        f"## СХЕМА\n{json.dumps(schema, ensure_ascii=False)[:3000]}\n\n"
        f"## КОНТЕКСТ СТРАНИЦЫ\n{page_context[:500]}"
    )

    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{DASHSCOPE_BASE}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read())
            result_text = raw["choices"][0]["message"]["content"]
    except Exception as e:
        return {
            "page_id": page_id,
            "entities": [],
            "relations": [],
            "model": f"api_error: {e}",
            "elapsed_s": time.time() - t0,
        }

    elapsed = time.time() - t0

    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            parsed = json.loads(result_text[j1:j2])
            parsed["page_id"] = page_id
            parsed["elapsed_s"] = round(elapsed, 1)
            return parsed
    except (json.JSONDecodeError, KeyError):
        pass

    return {
        "page_id": page_id,
        "entities": [],
        "relations": [],
        "model": "parse_failed",
        "elapsed_s": round(elapsed, 1),
    }


def map_all(schemas: dict[int, dict], page_contexts: dict[int, str], max_workers: int = MAX_WORKERS) -> list[dict]:
    """Маппит все страницы в онтологию параллельно."""
    api_key = str(DASHSCOPE_KEY)
    total = len(schemas)

    print(f"  Cloud ontology: {total} стр. × {max_workers} workers (DashScope {MODEL})")

    t0 = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_map_one, pid, schema, page_contexts.get(pid, ""), api_key): pid
            for pid, schema in schemas.items()
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            n_entities = len(result.get("entities", []))
            n_relations = len(result.get("relations", []))
            print(f"    p{result['page_id']}: {n_entities} entities, {n_relations} relations — {result.get('elapsed_s', '?')}s")

    results.sort(key=lambda r: r["page_id"])
    total_elapsed = time.time() - t0

    print(f"  Cloud ontology done: {total_elapsed:.1f}s total ({total_elapsed/total:.1f}s/стр)")

    return results