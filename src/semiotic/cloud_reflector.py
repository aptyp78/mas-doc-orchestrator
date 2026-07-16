"""Уровень 4: Прагматический рефлектор (Cloud — DashScope).

Использует qwen3.7-plus через DashScope для синтеза C-level рекомендаций.
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

REFLECTOR_PROMPT = """[РОЛЬ] Прагматический рефлектор
[ПРЕДМЕТ] Онтологическая модель страницы документа
[ЗАДАЧА] Синтезируй вывод для C-level руководителя
[ПРАВИЛА]
1. Оцени СТРАТЕГИЧЕСКУЮ ЗНАЧИМОСТЬ: почему это важно для российского бизнеса/государства?
2. Выдели КЛЮЧЕВЫЕ РИСКИ: что может пойти не так?
3. Выдели ВОЗМОЖНОСТИ: где окно для российских экономических операторов?
4. Дай RECOMMENDED ACTION: одно конкретное действие для C-level
5. Оцени УВЕРЕННОСТЬ: HIGH/MEDIUM/LOW — насколько данные поддерживают вывод
[ОГРАНИЧЕНИЕ] Не выдумывай. Только на основе онтологической модели. Вывод — для российского C-level.

Формат: JSON
{
  "strategic_significance": "string",
  "risks": ["string", ...],
  "opportunities": ["string", ...],
  "recommended_action": "string",
  "confidence": "HIGH|MEDIUM|LOW",
  "urgency": "HIGH|MEDIUM|LOW"
}"""


def _reflect_one(page_id: int, ontology: dict, domain_context: str, api_key: str) -> dict:
    """Синтезирует C-level вывод для одной страницы через DashScope."""
    t0 = time.time()

    prompt = (
        f"{REFLECTOR_PROMPT}\n\n"
        f"## ОНТОЛОГИЧЕСКАЯ МОДЕЛЬ\n{json.dumps(ontology, ensure_ascii=False)[:3000]}\n\n"
        f"## ДОМЕННЫЙ КОНТЕКСТ\n{domain_context[:300]}"
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
            "strategic_significance": "",
            "risks": [],
            "opportunities": [],
            "recommended_action": "",
            "confidence": "LOW",
            "urgency": "LOW",
            "elapsed_s": time.time() - t0,
            "error": str(e),
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
        "strategic_significance": "",
        "risks": [],
        "opportunities": [],
        "recommended_action": "",
        "confidence": "LOW",
        "urgency": "LOW",
        "elapsed_s": round(elapsed, 1),
    }


def reflect_all(ontologies: dict[int, dict], domain_context: str = "", max_workers: int = MAX_WORKERS) -> list[dict]:
    """Синтезирует C-level выводы для всех страниц параллельно."""
    api_key = str(DASHSCOPE_KEY)
    total = len(ontologies)

    print(f"  Cloud reflector: {total} стр. × {max_workers} workers (DashScope {MODEL})")

    t0 = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_reflect_one, pid, ontology, domain_context, api_key): pid
            for pid, ontology in ontologies.items()
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            action = result.get("recommended_action", "")[:80]
            urgency = result.get("urgency", "?")
            print(f"    p{result['page_id']}: [{urgency}] {action} — {result.get('elapsed_s', '?')}s")

    results.sort(key=lambda r: r["page_id"])
    total_elapsed = time.time() - t0

    print(f"  Cloud reflector done: {total_elapsed:.1f}s total ({total_elapsed/total:.1f}s/стр)")

    return results