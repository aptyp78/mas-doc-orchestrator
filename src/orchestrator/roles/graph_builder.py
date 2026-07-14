"""ОРП 6: Graph Builder.

Устанавливает связи между блоками через qwen3.6:35b.
"""

from __future__ import annotations

import json
import urllib.request

from src.utils.config import OLLAMA_LOCAL_BASE

ROLE = (
    "[РОЛЬ] Graph Builder\n"
    "[ОБЪЕКТ] Примитивы и контекстные данные\n"
    "[ПРАВИЛА] Связи: contains, adjacent_to, aligned_with, references.\n"
    "          edge confidence ≥ 0.8. Не более 3 hops.\n"
    "          Orphan-узлы → логировать с причиной.\n"
    "[ОГРАНИЧЕНИЕ] Не управляй итерациями."
)

PROMPT_TEMPLATE = (
    "{role}\n\n"
    "Примитивы: {primitives}\n"
    "Разрешения: {resolutions}\n"
    "Нарушения: {violations}\n"
    "Пространственный кэш: {spatial_cache}\n\n"
    "Выдай результат как JSON с полями:\n"
    "- graph_structure: {{nodes: [], edges: []}}\n"
    "- groups: [{{group_id, member_ids, theme}}]\n"
    "- orphans: [{{id, reason}}]\n"
    "- overall_confidence: float"
)

MODEL = "qwen3.6:35b"


def run(
    primitives: list[dict] | None = None,
    resolutions: list[dict] | None = None,
    violations: list[dict] | None = None,
    spatial_cache: dict | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.1,
) -> dict:
    """Строит граф связей между блоками.

    Args:
        primitives: примитивы от Visual Extractor
        resolutions: разрешения от Semantic Disambiguator
        violations: нарушения от Style Validator
        spatial_cache: пространственный кэш
        max_tokens: лимит токенов
        temperature: температура

    Returns:
        dict с graph_structure, groups, orphans, overall_confidence
    """
    prompt = PROMPT_TEMPLATE.format(
        role=ROLE,
        primitives=json.dumps(primitives or [], ensure_ascii=False),
        resolutions=json.dumps(resolutions or [], ensure_ascii=False),
        violations=json.dumps(violations or [], ensure_ascii=False),
        spatial_cache=json.dumps(spatial_cache or {}, ensure_ascii=False),
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

    # Пытаемся распарсить JSON
    try:
        json_start = result_text.find("{")
        json_end = result_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(result_text[json_start:json_end])
            gs = parsed.get("graph_structure", {"nodes": [], "edges": []})
            # Нормализация: content → label если label отсутствует
            for node in gs.get("nodes", []):
                if "label" not in node and "content" in node:
                    node["label"] = node["content"]
            # Нормализация рёбер: source_id → source, target_id → target
            for edge in gs.get("edges", []):
                if "source" not in edge and "source_id" in edge:
                    edge["source"] = edge["source_id"]
                if "target" not in edge and "target_id" in edge:
                    edge["target"] = edge["target_id"]
            return {
                "graph_structure": gs,
                "groups": parsed.get("groups", []),
                "orphans": parsed.get("orphans", []),
                "overall_confidence": parsed.get("overall_confidence", 0.5),
                "raw_output": result_text,
            }
    except (json.JSONDecodeError, KeyError):
        pass

    return {
        "graph_structure": {"nodes": [], "edges": []},
        "groups": [],
        "orphans": [],
        "overall_confidence": 0.0,
        "raw_output": result_text,
    }
