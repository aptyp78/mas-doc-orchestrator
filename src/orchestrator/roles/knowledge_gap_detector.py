"""ОРП 8: Knowledge Gap Detector.

Проверяет: достаточно ли знаний в весах модели для анализа доменов документа.
Если нет → KNOWLEDGE_GAP → эскалация (облачная модель / web search / human expert).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"

# Загружаем промпт из файла
PROMPT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "orchestrator" / "knowledge_gap_detector.md"

def _load_prompt() -> str:
    """Загружает промпт из .md файла — от первого [РОЛЬ] до конца."""
    if PROMPT_PATH.exists():
        content = PROMPT_PATH.read_text()
        # Находим начало промпта: первая строка с [РОЛЬ]
        idx = content.find("[РОЛЬ]")
        if idx >= 0:
            return content[idx:].strip()
    return ""


def run(domains: list[dict]) -> dict:
    """Проверяет компетентность модели в доменах документа.

    Args:
        domains: список доменов из domain_analyzer.detect_domain()

    Returns:
        dict с domain_checks, overall_assessment, recommendation
    """
    prompt = _load_prompt()
    if not prompt:
        return {
            "domain_checks": [],
            "overall_assessment": "PROCEED",
            "recommendation": "prompt_not_found",
        }

    # Формируем запрос: перечисляем домены
    domain_list = "\n".join(
        f"- {d['domain']} (confidence: {d.get('confidence_level', d.get('confidence', '?'))})"
        for d in domains
    )

    full_prompt = f"{prompt}\n\n## ДОМЕНЫ ДОКУМЕНТА\n{domain_list}"

    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": full_prompt}],
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

    try:
        json_start = result_text.find("{")
        json_end = result_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(result_text[json_start:json_end])
    except (json.JSONDecodeError, KeyError):
        pass

    return {
        "domain_checks": [],
        "overall_assessment": "PROCEED",
        "recommendation": "parse_failed",
        "raw_output": result_text,
    }