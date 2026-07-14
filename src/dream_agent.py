"""Dream Agent: фоновая консолидация графа знаний.

После batch-прогона анализирует накопленный граф:
1. Merge duplicate nodes — объединяет узлы, ссылающиеся на один факт
2. Flag contradictions — детектирует противоречия между документами
3. Gap detection — находит отсутствующие связи между контурами
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"

DREAM_PROMPT = """[РОЛЬ] Позиция консолидатора знаний
[ПРЕДМЕТ] Накопленный граф знаний из нескольких документов
[ПРАВИЛА]
1. Найди узлы с одинаковым смыслом, но разными ID → предложи merge
2. Найди противоречия: два узла утверждают противоположное → зафиксируй conflict
3. Найди gaps: контуры без связей, которые должны быть связаны → предложи edge
4. Оцени уверенность каждого действия: HIGH/MEDIUM/LOW
[ОГРАНИЧЕНИЕ]
- Не изменяй существующие узлы — только предлагай действия
- Не выдумывай связи. Только на основе имеющихся данных.
- Выводи строго JSON.

## СХЕМА JSON
{
  "merges": [
    {"node_ids": ["id1", "id2"], "merged_label": "string", "confidence": "HIGH|MEDIUM|LOW", "reason": "string"}
  ],
  "conflicts": [
    {"node_a": "id1", "node_b": "id2", "claim_a": "string", "claim_b": "string", "severity": "HIGH|MEDIUM|LOW"}
  ],
  "gaps": [
    {"from_contour": "string", "to_contour": "string", "suggested_edge_type": "string", "confidence": "HIGH|MEDIUM|LOW"}
  ],
  "summary": "string"
}"""


def run(
    graph_history: list[dict],
    output_dir: str | None = None,
) -> dict:
    """Запускает консолидацию графа знаний.

    Args:
        graph_history: список графов из предыдущих прогонов [{graph_structure, ...}, ...]
        output_dir: директория для сохранения результатов (None = не сохранять)

    Returns:
        dict с merges, conflicts, gaps, summary
    """
    if not graph_history:
        return {"merges": [], "conflicts": [], "gaps": [], "summary": "no_data"}

    # Собираем все узлы из всех графов
    all_nodes = []
    for g in graph_history:
        gs = g.get("graph_structure", {})
        all_nodes.extend(gs.get("nodes", []))

    # Собираем все рёбра
    all_edges = []
    for g in graph_history:
        gs = g.get("graph_structure", {})
        all_edges.extend(gs.get("edges", []))

    prompt = (
        f"{DREAM_PROMPT}\n\n"
        f"## УЗЛЫ ({len(all_nodes)})\n{json.dumps(all_nodes, ensure_ascii=False)[:4000]}\n\n"
        f"## РЁБРА ({len(all_edges)})\n{json.dumps(all_edges, ensure_ascii=False)[:2000]}"
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
            result = json.loads(result_text[json_start:json_end])
    except (json.JSONDecodeError, KeyError):
        result = {"merges": [], "conflicts": [], "gaps": [], "summary": "parse_failed"}

    # Сохраняем
    if output_dir:
        out_path = Path(output_dir) / f"dream_{int(time.time())}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result