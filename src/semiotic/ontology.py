"""Уровень 3: Онтологический маппер (Activity Theory).

Берёт схему (из уровня 2) и извлекает структуру деятельности по Activity Theory (Engeström):
- Субъект → Кто действует? (автор, организация, сообщество)
- Объект → На что направлена деятельность? (продукт, услуга, проблема)
- Инструменты → С помощью чего? (технологии, методы, ресурсы)
- Цель → Зачем? (мотивы, результаты, эффекты)
- Сообщество → Кто участвует? (стейкхолдеры, аудитория)
- Правила → Какие ограничения? (нормы, стандарты, барьеры)
- Разделение труда → Кто что делает? (роли, функции)

Любой документ — это след деятельности. Структура деятельности универсальна.

Использует qwen3.6:35b для онтологического анализа.
"""

from __future__ import annotations

import json
import urllib.request

from src.utils.config import OLLAMA_LOCAL_BASE
from src.utils.prompt_loader import load_prompt

MODEL = "qwen3.6:35b"

ONTOLOGY_PROMPT = load_prompt("semiotic/ontology")


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