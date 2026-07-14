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
    "Примитивы (с номерами страниц): {primitives}\n"
    "Разрешения терминов: {resolutions}\n"
    "Нарушения: {violations}\n"
    "Доменный контекст: {document_context}\n\n"
    "Построй граф знаний документа:\n"
    "- nodes: каждый узел ДОЛЖЕН иметь source_page (номер страницы из примитива)\n"
    "- edges: смысловые связи между узлами\n"
    "- groups: тематические группы\n"
    "- orphans: узлы без связей\n\n"
    "Выдай JSON:\n"
    "- graph_structure: {{nodes: [{{id, label, type, source_page}}], edges: [{{from, to, relation}}]}}\n"
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
    max_primitives: int = 40,
    temperature: float = 0.1,
) -> dict:
    """Строит граф знаний с provenance (source_page).

    Args:
        primitives: примитивы с source_page
        resolutions: разрешения терминов
        violations: нарушения стиля
        spatial_cache: доменный контекст {domain, subject, object, kgd_assessment}
        max_tokens: лимит токенов
        max_primitives: макс. число примитивов
        temperature: температура
    """
    ctx = spatial_cache or {}
    primitives_str = json.dumps((primitives or [])[:max_primitives], ensure_ascii=False)
    doc_context = json.dumps({
        "domain": ctx.get("domain", ""),
        "domains": ctx.get("domains", []),
        "subject": ctx.get("subject", ""),
        "object": ctx.get("object", ""),
        "kgd": ctx.get("kgd_assessment", "PROCEED"),
    }, ensure_ascii=False)

    prompt = PROMPT_TEMPLATE.format(
        role=ROLE,
        primitives=primitives_str,
        resolutions=json.dumps(resolutions or [], ensure_ascii=False)[:1500],
        violations=json.dumps(violations or [], ensure_ascii=False)[:500],
        document_context=doc_context,
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
