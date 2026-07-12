"""ОРП 7: External Context Resolver.

Разрешает SEMANTIC_GAP через внешние источники в закрытом контуре.
Без LLM — работает с локальным глоссарием.
"""

from __future__ import annotations

import json
import os

ROLE = (
    "[РОЛЬ] External Context Resolver\n"
    "[ОБЪЕКТ] Единицы с SEMANTIC_GAP\n"
    "[ПРАВИЛА] Ищи в: локальный глоссарий → доменная онтология → human-in-the-loop.\n"
    "          Не найдено → EXTERNAL_GAP (требуется пополнение глоссария).\n"
    "[ОГРАНИЧЕНИЕ] Не обращайся к облачным API. Не извлекай смысл из текста документа."
)

PROMPT = ROLE  # Эта роль не использует LLM

# Путь к глоссарию
GLOSSARY_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "glossary", "psb_org_structure.json")


def _load_glossary() -> dict:
    """Загружает локальный глоссарий."""
    if os.path.exists(GLOSSARY_PATH):
        with open(GLOSSARY_PATH) as f:
            return json.load(f)
    return {}


def run(semantic_gaps: list[dict], glossary: dict | None = None) -> dict:
    """Разрешает SEMANTIC_GAP через внешние источники.

    Args:
        semantic_gaps: список gap-записей от Semantic Disambiguator
        glossary: словарь термин→значение (если None — загружается из файла)

    Returns:
        dict с resolved, external_gaps, glossary_updates
    """
    if glossary is None:
        glossary = _load_glossary()

    resolved: list[dict] = []
    external_gaps: list[dict] = []
    glossary_updates: list[dict] = []

    for gap in semantic_gaps:
        term = gap.get("term", "")

        # 1. Поиск в глоссарии
        if term in glossary:
            resolved.append(
                {
                    "term": term,
                    "meaning": glossary[term],
                    "source": "glossary",
                    "confidence": 0.90,
                }
            )
            continue

        # 2. Поиск по частичному совпадению
        found = False
        for key, value in glossary.items():
            if term.lower() in key.lower() or key.lower() in term.lower():
                resolved.append(
                    {
                        "term": term,
                        "meaning": value,
                        "source": "glossary",
                        "confidence": 0.70,
                    }
                )
                found = True
                break

        if found:
            continue

        # 3. Не найдено → EXTERNAL_GAP
        external_gaps.append(
            {
                "term": term,
                "reason": "not_in_glossary",
                "action": "populate_glossary",
            }
        )

    # L1: проверка покрытия
    total = len(semantic_gaps)
    resolved_count = len(resolved)
    coverage = resolved_count / total if total > 0 else 1.0

    return {
        "resolved": resolved,
        "external_gaps": external_gaps,
        "glossary_updates": glossary_updates,
        "coverage": round(coverage, 2),
    }
