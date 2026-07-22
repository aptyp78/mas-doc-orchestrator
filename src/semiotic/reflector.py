"""Уровень 4: Прагматический рефлектор (Activity Theory).

Берёт онтологическую модель деятельности (из уровня 3) и синтезирует вывод для C-level:
- Что это значит для руководителя?
- Какие риски в деятельности? Какие возможности?
- Какой recommended action для оптимизации деятельности?

Использует qwen3.6:35b.
"""

from __future__ import annotations

import json
import urllib.request

from src.utils.config import OLLAMA_LOCAL_BASE
from src.utils.prompt_loader import load_prompt

MODEL = "qwen3.6:35b"

REFLECTOR_PROMPT = load_prompt("semiotic/reflector")


def reflect(ontology: dict, domain_context: str = "") -> dict:
    """Синтезирует C-level вывод из онтологической модели."""
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

    return {"strategic_significance": "", "risks": [], "opportunities": [], "recommended_action": "", "confidence": "LOW", "urgency": "LOW"}