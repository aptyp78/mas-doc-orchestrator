"""SMD Domain Analyzer: Determine document domain through Activity Theory (Engeström).

Работает на Universal Representation (выход нормализатора), а не на сыром PDF.
СМД-подход: домен определяется не по ключевым словам, а по структуре деятельности.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from src.utils.config import OLLAMA_LOCAL_BASE
from src.utils.prompt_loader import load_prompt


# Путь к директории с глоссариями
GLOSSARY_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "glossary"


def _match_glossaries(domains: list[dict]) -> list[str]:
    """Fuzzy-матчинг эмерджентных доменов с глоссариями.

    Глоссарий сам описывает свои домены через _metadata.domains (ключевые слова).
    Матчинг: пересечение слов между именем домена и ключевыми словами глоссария.

    Returns:
        список имён файлов глоссариев (без пути)
    """
    if not GLOSSARY_DIR.exists():
        return []

    matched = []
    for glossary_file in GLOSSARY_DIR.glob("*.json"):
        try:
            with open(glossary_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        meta = data.get("_metadata", {})
        keywords = meta.get("domains", [])
        if not keywords:
            continue

        # Проверяем пересечение: есть ли keyword из глоссария в имени домена
        for domain_info in domains:
            domain_name = domain_info.get("domain", "").lower()
            for kw in keywords:
                if kw.lower() in domain_name:
                    matched.append(glossary_file.name)
                    break  # достаточно одного совпадения на домен
            else:
                continue
            break  # глоссарий уже добавлен

    return list(set(matched))  # уникальные


# SMD Activity Theory prompt for qwen3.6:35b
DOMAIN_ANALYSIS_PROMPT = load_prompt("orchestrator/domain_analyzer")


def _build_context(universal_repr: dict) -> dict:
    """Строит контекст для SMD-анализа из Universal Representation."""
    metadata = universal_repr.get("metadata", {})
    pages = universal_repr.get("pages", [])

    # Собираем текстовое содержимое (text + ocr_text)
    text_parts = []
    for page in pages:
        for elem in page.get("elements", []):
            if elem["type"] in ("text", "ocr_text") and elem.get("content"):
                text_parts.append(elem["content"])

    # Собираем summary по типам страниц
    page_types = universal_repr.get("stats", {}).get("page_types", {})

    return {
        "metadata": metadata,
        "text_snippet": "\n".join(text_parts)[:3000],
        "page_types": page_types,
        "total_pages": len(pages),
        "has_images": any(
            any(e["type"] == "image" for e in p.get("elements", []))
            for p in pages
        ),
        "has_vectors": any(
            any(e["type"] == "vector" for e in p.get("elements", []))
            for p in pages
        ),
    }


def _run_smd_analysis(context: dict) -> dict:
    """Run SMD domain analysis through qwen3.6:35b."""
    prompt = (
        f"{DOMAIN_ANALYSIS_PROMPT}\n\n"
        f"## МЕТАДАННЫЕ:\n{json.dumps(context['metadata'], ensure_ascii=False)}\n\n"
        f"## СТРУКТУРА ДОКУМЕНТА:\n"
        f"- Страниц: {context['total_pages']}\n"
        f"- Типы страниц: {json.dumps(context['page_types'], ensure_ascii=False)}\n"
        f"- Есть изображения: {context['has_images']}\n"
        f"- Есть векторные пути: {context['has_vectors']}\n\n"
        f"## ТЕКСТОВОЕ СОДЕРЖИМОЕ:\n{context['text_snippet']}"
    )

    data = json.dumps({
        "model": "qwen3.6:35b",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048,
        "temperature": 0.1,
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = json.loads(resp.read())
        result_text = raw["message"]["content"]

    # Parse JSON from response
    try:
        json_start = result_text.find("{")
        json_end = result_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(result_text[json_start:json_end])
            domains = parsed.get("domains", [])
            primary = parsed.get("primary_domain", "")
            # Fallback for old format: single detected_domain
            if not domains and parsed.get("detected_domain"):
                domains = [{
                    "domain": parsed["detected_domain"],
                    "confidence": float(parsed.get("confidence", 0.5)),
                    "rationale": parsed.get("reasoning", ""),
                }]
                primary = parsed["detected_domain"]
            return {
                "subject": parsed.get("subject", ""),
                "object": parsed.get("object", ""),
                "tools": parsed.get("tools", []),
                "rules": parsed.get("rules", []),
                "community": parsed.get("community", []),
                "division_of_labor": parsed.get("division_of_labor"),
                "domains": domains,
                "primary_domain": primary,
                "reasoning": parsed.get("reasoning", ""),
                "raw_output": result_text,
            }
    except (json.JSONDecodeError, KeyError):
        pass

    return {
        "subject": "",
        "object": "",
        "tools": [],
        "rules": [],
        "community": [],
        "division_of_labor": None,
        "domains": [],
        "primary_domain": "other",
        "reasoning": "Failed to parse SMD analysis output",
        "raw_output": result_text,
    }


def detect_domain(universal_repr: dict) -> dict:
    """
    Detect document domain(s) from Universal Representation.

    Работает на выходе нормализатора — не на сыром PDF.
    Поддерживает мульти-доменные документы (например, banking + defense).

    Args:
        universal_repr: выход pdf_normalizer.normalize()

    Returns:
        dict with domains[], primary_domain, SMD elements, glossaries
    """
    # Строим контекст из Universal Representation
    context = _build_context(universal_repr)

    # Запускаем SMD-анализ через qwen3.6:35b
    analysis_result = _run_smd_analysis(context)

    # Собираем глоссарии через fuzzy-матчинг с эмерджентными доменами
    glossaries_to_use = _match_glossaries(analysis_result.get("domains", []))
    if not glossaries_to_use:
        glossaries_to_use = ["psb_org_structure.json"]  # fallback

    return {
        **analysis_result,
        "page_types": context["page_types"],
        "glossaries_to_use": glossaries_to_use,
        "metadata_for_context": context["metadata"],
    }