"""ОРП 7: External Context Resolver.

Разрешает SEMANTIC_GAP через: локальный глоссарий → LLM-кандидат → external.
Никогда не блокирует пайплайн — EXTERNAL_GAP = кандидат на пополнение глоссария.
"""

from __future__ import annotations

import json
import os
import urllib.request

from src.utils.config import OLLAMA_LOCAL_BASE

ROLE = (
    "[РОЛЬ] External Context Resolver\n"
    "[ОБЪЕКТ] Единицы с SEMANTIC_GAP\n"
    "[ПРАВИЛА] Ищи в: локальный глоссарий → LLM-предположение → кандидат в глоссарий.\n"
    "          Не блокируй пайплайн. EXTERNAL_GAP = кандидат, не ошибка.\n"
    "[ОГРАНИЧЕНИЕ] Не обращайся к облачным API. Не извлекай смысл из текста документа."
)

PROMPT = ROLE

RESOLVE_CANDIDATE_PROMPT = (
    "[РОЛЬ] Terminology Resolver\n"
    "[ЗАДАЧА] Предположи значение термина/аббревиатуры на основе контекста\n"
    "[ПРАВИЛА] Если уверен — дай определение. Если нет — скажи 'UNCLEAR'.\n"
    "[ОГРАНИЧЕНИЕ] Не выдумывай. Confidence < 0.7 → UNCLEAR.\n\n"
    "Термин: {term}\n"
    "Контекст: {context}\n\n"
    "Формат: JSON с полями: meaning (string), confidence (float), source (string)"
)


def _resolve_via_llm(term: str, context: str) -> dict | None:
    """Пытается разрешить термин через LLM (qwen3.6:35b)."""
    prompt = RESOLVE_CANDIDATE_PROMPT.format(term=term, context=context[:500])

    data = json.dumps({
        "model": "qwen3.6:35b",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.1,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read())
            result_text = raw["message"]["content"]

        json_start = result_text.find("{")
        json_end = result_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(result_text[json_start:json_end])
            if parsed.get("meaning") and parsed.get("meaning", "").upper() != "UNCLEAR":
                return {
                    "term": term,
                    "meaning": parsed["meaning"],
                    "confidence": float(parsed.get("confidence", 0.5)),
                    "source": parsed.get("source", "llm_candidate"),
                }
    except Exception:
        pass

    return None


def _load_glossary(domain: str | None = None) -> dict:
    """Загружает локальный глоссарий. Поддерживает новый формат с _metadata и terms."""
    # Ищем глоссарий в data/glossary/
    glossary_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "glossary")
    glossary_path = None

    if domain is not None and os.path.exists(glossary_dir):
        # Ищем файл глоссария, чьи _metadata.domains содержат domain
        for fname in os.listdir(glossary_dir):
            if fname.endswith(".json"):
                fpath = os.path.join(glossary_dir, fname)
                try:
                    with open(fpath) as f:
                        data = json.load(f)
                    meta = data.get("_metadata", {})
                    keywords = meta.get("domains", [])
                    if any(kw.lower() in domain.lower() for kw in keywords):
                        glossary_path = fpath
                        break
                except (json.JSONDecodeError, OSError):
                    continue

    # Fallback
    if glossary_path is None:
        glossary_path = os.path.join(glossary_dir, "psb_org_structure.json")

    if os.path.exists(glossary_path):
        with open(glossary_path) as f:
            data = json.load(f)
            # Новый формат: terms внутри
            return data.get("terms", data)  # fallback: старый плоский формат
    return {}


def run(semantic_gaps: list[dict], glossary: dict | None = None, domain: str | None = None, context: str = "") -> dict:
    """Разрешает SEMANTIC_GAP: глоссарий → LLM-кандидат → external.

    Никогда не блокирует пайплайн. EXTERNAL_GAP = кандидат на пополнение.

    Args:
        semantic_gaps: список gap-записей от Semantic Disambiguator
        glossary: словарь термин→значение (если None — загружается из файла)
        domain: предметный домен (для выбора глоссария)
        context: текстовый контекст для LLM-разрешения

    Returns:
        dict с resolved, external_gaps, candidates, coverage
    """
    if glossary is None:
        glossary = _load_glossary(domain=domain)

    resolved: list[dict] = []
    external_gaps: list[dict] = []
    candidates: list[dict] = []

    for gap in semantic_gaps:
        term = gap.get("term", "")

        # 1. Поиск в глоссарии
        if term in glossary:
            resolved.append({
                "term": term,
                "meaning": glossary[term],
                "source": "glossary",
                "confidence": 0.90,
            })
            continue

        # 2. Частичное совпадение
        found = False
        for key, value in glossary.items():
            if term.lower() in key.lower() or key.lower() in term.lower():
                resolved.append({
                    "term": term,
                    "meaning": value,
                    "source": "glossary",
                    "confidence": 0.70,
                })
                found = True
                break
        if found:
            continue

        # 3. LLM-разрешение
        llm_result = _resolve_via_llm(term, context)
        if llm_result and llm_result["confidence"] >= 0.7:
            candidates.append(llm_result)
            resolved.append({
                "term": term,
                "meaning": llm_result["meaning"],
                "source": "llm_candidate",
                "confidence": llm_result["confidence"],
            })
            continue

        # 4. Не найдено → EXTERNAL_GAP (кандидат, не ошибка)
        external_gaps.append({
            "term": term,
            "reason": "not_in_glossary",
            "action": "add_to_glossary_candidate",
        })

    total = len(semantic_gaps)
    resolved_count = len(resolved)
    coverage = resolved_count / total if total > 0 else 1.0

    return {
        "resolved": resolved,
        "external_gaps": external_gaps,
        "candidates": candidates,
        "coverage": round(coverage, 2),
    }
