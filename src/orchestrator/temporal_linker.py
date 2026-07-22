"""Sub-3: Temporal Linker — временное измерение графа.

Расширяет cross_page_linker отношениями во времени:
- PRECEDES: A предшествует B (логически или хронологически)
- CAUSES: A вызывает B (причинно-следственная связь)
- ENABLES: A создаёт условия для B
- BLOCKS: A препятствует B

В отличие от entity-based linker (который ищет общие сущности),
temporal linker ищет причинно-следственные цепи и последовательности.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass, field

from src.utils.config import OLLAMA_LOCAL_BASE
from src.utils.prompt_loader import load_prompt

MODEL = "qwen3.6:35b"


@dataclass
class TemporalEdge:
    """Временное ребро графа."""
    source_page: int
    target_page: int
    relation_type: str  # PRECEDES, CAUSES, ENABLES, BLOCKS
    strength: float
    explanation: str
    evidence: str = ""  # цитата из контекста


def _call_ollama(prompt: str, max_tokens: int = 512) -> str:
    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.1, "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat", data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["message"]["content"]


def _parse_json(text: str) -> dict:
    try:
        j1, j2 = text.find("{"), text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass
    return {}


class TemporalLinker:
    """Находит причинно-следственные и временные связи между зонами."""

    PAIR_PROMPT = load_prompt("orchestrator/temporal_linker_pair")

    CHAIN_PROMPT = load_prompt("orchestrator/temporal_linker_chain")

    def __init__(self):
        self.edges: list[TemporalEdge] = []
        self._adj: dict[int, list[TemporalEdge]] = defaultdict(list)

    def find_relations(self, schemas: dict[int, dict], max_pairs: int = 50) -> list[TemporalEdge]:
        """Находит временные связи между страницами."""
        page_ids = sorted(schemas.keys())
        n_pages = len(page_ids)

        pairs = []
        for i in range(n_pages):
            for j in range(i + 1, min(n_pages, i + 5)):  # близкие страницы
                pairs.append((page_ids[i], page_ids[j]))

        pairs = pairs[:max_pairs]
        print(f"  TemporalLinker: {len(pairs)} pairs")
        t0 = time.time()
        edges_found = 0

        for a_id, b_id in pairs:
            schema_a = schemas[a_id]
            schema_b = schemas[b_id]
            content_a = json.dumps(schema_a, ensure_ascii=False)[:1500]
            content_b = json.dumps(schema_b, ensure_ascii=False)[:1500]

            prompt = self.PAIR_PROMPT.format(
                page_a=a_id, content_a=content_a,
                page_b=b_id, content_b=content_b,
            )
            result = _parse_json(_call_ollama(prompt, max_tokens=512))

            rel_type = result.get("relation_type")
            if rel_type and rel_type != "none":
                strength = result.get("strength", 0.5)
                if strength > 0.3:
                    edge = TemporalEdge(
                        source_page=a_id, target_page=b_id,
                        relation_type=rel_type, strength=strength,
                        explanation=result.get("explanation", ""),
                        evidence=result.get("evidence", ""),
                    )
                    self.edges.append(edge)
                    self._adj[a_id].append(edge)
                    edges_found += 1

        elapsed = time.time() - t0
        print(f"  TemporalLinker: {edges_found} edges — {elapsed:.1f}s")
        return self.edges

    def get_causal_chain(self, start_page: int, end_page: int) -> list[TemporalEdge] | None:
        """Находит причинную цепь между двумя страницами."""
        visited = {start_page}
        queue = deque([(start_page, [])])

        while queue:
            current, path = queue.popleft()
            if current == end_page:
                return path

            for edge in self._adj.get(current, []):
                neighbor = edge.target_page
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [edge]))

        return None

    def get_chains(self) -> list[dict]:
        """Выделяет причинные цепи длиной ≥2."""
        chains = []
        visited_edges = set()

        for start in self._adj:
            for edge1 in self._adj[start]:
                for edge2 in self._adj.get(edge1.target_page, []):
                    if edge2.relation_type in ("CAUSES", "ENABLES"):
                        chain_id = f"{edge1.source_page}_{edge1.target_page}_{edge2.target_page}"
                        if chain_id not in visited_edges:
                            visited_edges.add(chain_id)
                            chains.append({
                                "path": [edge1.source_page, edge1.target_page, edge2.target_page],
                                "relations": [edge1.relation_type, edge2.relation_type],
                                "description": f"{edge1.explanation} → {edge2.explanation}",
                            })

        return chains

    def to_dict(self) -> dict:
        return {
            "edges": [
                {
                    "source_page": e.source_page, "target_page": e.target_page,
                    "relation_type": e.relation_type, "strength": e.strength,
                    "explanation": e.explanation, "evidence": e.evidence,
                }
                for e in self.edges
            ],
            "total_edges": len(self.edges),
            "chains": self.get_chains(),
        }