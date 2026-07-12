"""ОРП 2: Semantic Disambiguator.

Разрешает аббревиатуры и термины через qwen3.6:35b.
"""

from __future__ import annotations

import json
import urllib.request

from src.utils.config import OLLAMA_LOCAL_BASE

ROLE = (
    "[РОЛЬ] Semantic Disambiguator\n"
    "[ОБЪЕКТ] Текстовые фрагменты и контекстный кэш\n"
    "[ПРАВИЛА] confidence < 0.7 → SEMANTIC_GAP. Кэш ≤ 500 ключей. "
    "Связывание ≥90% по контексту.\n"
    "[ОГРАНИЧЕНИЕ] Не интерпретируй визуальные элементы."
)

PROMPT_TEMPLATE = (
    "{role}\n\n"
    "Текст: {text_chunks}\n"
    "Кэш: {context_cache}\n\n"
    "Выдай результат как JSON с полями:\n"
    "- resolutions: [{{original, resolved, confidence, source_context}}]\n"
    "- semantic_gaps: [{{term, alternatives, action}}]\n"
    "- context_cache_snapshot: {{}}\n"
    "Для каждого термина: если confidence < 0.7 → помечай как SEMANTIC_GAP."
)

MODEL = "qwen3.6:35b"


def run(
    text_chunks: str,
    context_cache: dict | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> dict:
    """Разрешает аббревиатуры и термины в тексте.

    Args:
        text_chunks: текст для анализа
        context_cache: предыдущий кэш разрешений
        max_tokens: лимит токенов
        temperature: температура

    Returns:
        dict с resolutions, semantic_gaps, context_cache_snapshot
    """
    prompt = PROMPT_TEMPLATE.format(
        role=ROLE,
        text_chunks=text_chunks,
        context_cache=json.dumps(context_cache or {}, ensure_ascii=False),
    )

    data = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
    ).encode()

    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = json.loads(resp.read())
        result_text = raw["message"]["content"]

    # Пытаемся распарсить JSON из ответа
    try:
        # Ищем JSON в ответе
        json_start = result_text.find("{")
        json_end = result_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(result_text[json_start:json_end])
            return {
                "resolutions": parsed.get("resolutions", []),
                "semantic_gaps": parsed.get("semantic_gaps", []),
                "context_cache_snapshot": parsed.get("context_cache_snapshot", {}),
                "raw_output": result_text,
            }
    except (json.JSONDecodeError, KeyError):
        pass

    # Fallback: возвращаем сырой текст
    return {
        "resolutions": [],
        "semantic_gaps": [{"term": "parse_error", "alternatives": [], "action": "flag_human"}],
        "context_cache_snapshot": {},
        "raw_output": result_text,
    }
