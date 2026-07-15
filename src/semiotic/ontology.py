"""Уровень 3: Онтологический маппер.

Берёт схему (из уровня 2) и привязывает её элементы к предметной онтологии:
- Кто действует? → Геополитический актор, Корпорация, Государство
- Что является объектом? → Критический минерал, Технология, Рынок
- Какие отношения? → Конкуренция, Зависимость, Контроль, Кооперация
- Какие метрики? → Доля рынка, Процент зависимости, Объём инвестиций

Использует qwen3.6:35b для онтологического анализа.
"""

from __future__ import annotations

import json
import urllib.request

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"

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


def map_to_ontology(schema: dict, page_context: str = "") -> dict:
    """Привязывает схему к онтологии."""
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
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat",
        data=data, headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = json.loads(resp.read())
        result_text = raw["message"]["content"]

    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(result_text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass

    return {"entities": [], "relations": [], "model": "parse_failed"}