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
    max_tokens: int = 2048,
    max_prompt_chars: int = 4000,
    temperature: float = 0.1,
) -> dict:
    """Строит граф связей между блоками.

    Args:
        primitives: примитивы (ограничены max_prompt_chars)
        resolutions: разрешения
        violations: нарушения
        spatial_cache: пространственный кэш
        max_tokens: лимит токенов ответа
        max_prompt_chars: макс. размер промпта
        temperature: температура
    """
    primitives_str = json.dumps(primitives or [], ensure_ascii=False)[:max_prompt_chars // 2]
    resolutions_str = json.dumps(resolutions or [], ensure_ascii=False)[:max_prompt_chars // 4]
    violations_str = json.dumps(violations or [], ensure_ascii=False)[:max_prompt_chars // 8]
    spatial_str = json.dumps(spatial_cache or {}, ensure_ascii=False)[:max_prompt_chars // 8]

    prompt = PROMPT_TEMPLATE.format(
        role=ROLE,
        primitives=primitives_str,
        resolutions=resolutions_str,
        violations=violations_str,
        spatial_cache=spatial_str,
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
            # Нормализация рёбер: from→source, to→target, relation→type
            for edge in gs.get("edges", []):
                if "source" not in edge:
                    edge["source"] = edge.get("from", edge.get("source_id", ""))
                if "target" not in edge:
                    edge["target"] = edge.get("to", edge.get("target_id", ""))
                if "type" not in edge:
                    edge["type"] = edge.get("relation", edge.get("edge_type", "references"))
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
