"""Шаг 2: Cross-Page Synthesis Layer — кросс-страничный семантический граф.

Связывает онтологии разных страниц отношениями:
- КАСКАДНЫЙ_ЭФФЕКТ, КОНФЛИКТ_ИНТЕРЕСОВ, РЕСУРСНАЯ_ЗАВИСИМОСТЬ, ПРИЧИННАЯ_СВЯЗЬ, ТЕМАТИЧЕСКАЯ_БЛИЗОСТЬ

Использует adjacency list (без внешних зависимостей) + локальную Ollama.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections import defaultdict, deque

from src.utils.config import OLLAMA_LOCAL_BASE
from src.utils.prompt_loader import load_prompt

MODEL = "qwen3.6:35b"


def _call_ollama(prompt: str, max_tokens: int = 2048) -> str:
    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.1, "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat", data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["message"]["content"]


def _parse_json(text: str) -> dict:
    try:
        j1, j2 = text.find("{"), text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass
    return {}


class SimpleGraph:
    """Простой граф на adjacency list (без NetworkX)."""

    def __init__(self):
        self.nodes: dict[int, dict] = {}
        self.edges: list[tuple[int, int, dict]] = []
        self._adj: dict[int, list[int]] = defaultdict(list)

    def add_node(self, pid: int, **attrs):
        self.nodes[pid] = attrs

    def add_edge(self, u: int, v: int, **attrs):
        self.edges.append((u, v, attrs))
        self._adj[u].append(v)
        self._adj[v].append(u)

    def nodes_list(self) -> list[int]:
        return list(self.nodes.keys())

    def out_degree(self, pid: int) -> int:
        return sum(1 for e in self.edges if e[0] == pid)

    def in_degree(self, pid: int) -> int:
        return sum(1 for e in self.edges if e[1] == pid)

    def number_of_edges(self) -> int:
        return len(self.edges)

    def to_undirected(self) -> "SimpleGraph":
        g = SimpleGraph()
        g.nodes = dict(self.nodes)
        g.edges = list(self.edges)
        g._adj = defaultdict(list, {k: list(v) for k, v in self._adj.items()})
        return g

    def connected_components(self) -> list[set[int]]:
        visited = set()
        components = []
        for node in self.nodes:
            if node not in visited:
                comp = set()
                queue = deque([node])
                while queue:
                    n = queue.popleft()
                    if n not in visited:
                        visited.add(n)
                        comp.add(n)
                        for neighbor in self._adj.get(n, []):
                            if neighbor not in visited:
                                queue.append(neighbor)
                components.append(comp)
        return components


class CrossPageSynthesizer:
    """Синтезирует связи между страницами документа."""

    PAIR_PROMPT = load_prompt("orchestrator/cross_page_synthesizer_pair")

    GLOBAL_PROMPT = load_prompt("orchestrator/cross_page_synthesizer_global")

    def __init__(self):
        self.graph = SimpleGraph()

    def build_graph(self, ontologies: dict[int, dict], max_pairs: int = 50) -> SimpleGraph:
        """Строит граф связей между страницами."""
        page_ids = sorted(ontologies.keys())
        n_pages = len(page_ids)

        for pid in page_ids:
            ont = ontologies[pid]
            entities = [e.get("name", "") for e in ont.get("entities", [])[:3]]
            model = ont.get("model", "")[:100]
            self.graph.add_node(pid, entities=entities, model=model)

        pairs = []
        for i in range(n_pages):
            for j in range(i + 1, min(n_pages, i + 10)):
                pairs.append((page_ids[i], page_ids[j]))
        pairs = pairs[:max_pairs]

        print(f"  Cross-page synthesis: {n_pages} pages, {len(pairs)} pairs")
        t0 = time.time()
        edges_found = 0

        for a_id, b_id in pairs:
            a_ont = json.dumps(ontologies[a_id], ensure_ascii=False)[:1500]
            b_ont = json.dumps(ontologies[b_id], ensure_ascii=False)[:1500]

            prompt = self.PAIR_PROMPT.format(a_id=a_id, a_ontology=a_ont, b_id=b_id, b_ontology=b_ont)
            result = _parse_json(_call_ollama(prompt, max_tokens=512))

            rel_type = result.get("relation_type")
            if rel_type and rel_type != "null" and rel_type != "None":
                strength = result.get("strength", 0.5)
                if strength > 0.3:
                    self.graph.add_edge(a_id, b_id, type=rel_type, strength=strength,
                                        explanation=result.get("explanation", ""),
                                        direction=result.get("direction", "bidirectional"))
                    edges_found += 1

        elapsed = time.time() - t0
        print(f"  Cross-page synthesis: {edges_found} edges found — {elapsed:.1f}s")
        return self.graph

    def get_clusters(self) -> list[dict]:
        undirected = self.graph.to_undirected()
        clusters = []
        for component in undirected.connected_components():
            if len(component) > 1:
                pages = sorted(component)
                entities = []
                for p in pages:
                    entities.extend(self.graph.nodes[p].get("entities", []))
                top_entities = list(dict.fromkeys(entities))[:5]
                clusters.append({"pages": pages, "size": len(pages), "key_entities": top_entities})
        return sorted(clusters, key=lambda c: c["size"], reverse=True)

    def get_leverage_points(self) -> list[dict]:
        scores = {}
        for node in self.graph.nodes_list():
            scores[node] = self.graph.out_degree(node) + self.graph.in_degree(node)
        top = sorted(scores.items(), key=lambda x: -x[1])[:10]
        return [{"page": pid, "centrality": score, "entities": self.graph.nodes[pid].get("entities", [])}
                for pid, score in top if score > 0]

    def synthesize_macro_structure(self, ontologies: dict[int, dict]) -> dict:
        if self.graph.number_of_edges() == 0:
            return {"clusters": [], "latent_drivers": [], "leverage_points": [], "strategic_contradictions": []}

        summary_parts = []
        for pid in sorted(ontologies.keys())[:30]:
            ont = ontologies[pid]
            model = ont.get("model", "")[:100]
            if model:
                summary_parts.append(f"p{pid}: {model}")

        edges = [f"p{u} --[{d['type']}]--> p{v} ({d.get('explanation', '')})"
                 for u, v, d in self.graph.edges]

        prompt = self.GLOBAL_PROMPT.format(n_pages=len(ontologies), summary="\n".join(summary_parts),
                                           edges="\n".join(edges[:30]))
        return _parse_json(_call_ollama(prompt, max_tokens=2048))

    def to_dict(self) -> dict:
        return {
            "nodes": [{"page": n, "entities": self.graph.nodes[n].get("entities", []),
                       "model": self.graph.nodes[n].get("model", "")}
                      for n in self.graph.nodes_list()],
            "edges": [{"from": u, "to": v, "type": d["type"], "strength": d["strength"],
                       "explanation": d.get("explanation", "")}
                      for u, v, d in self.graph.edges],
            "clusters": self.get_clusters(),
            "leverage_points": self.get_leverage_points(),
        }