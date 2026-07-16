"""Шаг 2: Cross-Page Entity Graph — граф связей между зонами.

Ищет совпадения сущностей между зонами разных страниц.
Строит граф: {source_zone_id, target_zone_id, relation_type, confidence}.

Использует:
- Текстовое совпадение (fuzzy) для быстрого поиска
- Эмбеддинги для семантической близости
- Локальную Ollama для верификации связей
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from collections import defaultdict
from difflib import SequenceMatcher

from src.orchestrator.zone_store import ZoneStore, Zone
from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"


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


def _fuzzy_match(a: str, b: str, threshold: float = 0.6) -> bool:
    """Нечёткое текстовое совпадение."""
    a_clean = re.sub(r'[^\w\s]', '', a.lower()).strip()
    b_clean = re.sub(r'[^\w\s]', '', b.lower()).strip()
    if len(a_clean) < 3 or len(b_clean) < 3:
        return False
    return SequenceMatcher(None, a_clean, b_clean).ratio() >= threshold


class CrossPageLinker:
    """Строит граф связей между зонами."""

    VERIFY_PROMPT = """[РОЛЬ] Верификатор кросс-страничных связей
[ПРЕДМЕТ] Две зоны документа с общими сущностями
[ЗАДАЧА] Определи тип связи между зонами
[ПРАВИЛА]
1. Типы: КАСКАДНЫЙ_ЭФФЕКТ, КОНФЛИКТ_ИНТЕРЕСОВ, РЕСУРСНАЯ_ЗАВИСИМОСТЬ, ПРИЧИННАЯ_СВЯЗЬ, ТЕМАТИЧЕСКАЯ_БЛИЗОСТЬ
2. Если связи нет — "none"
3. Оцени strength: 0.0-1.0
[ОГРАНИЧЕНИЕ] Только если связь действительно есть.

Формат: JSON
{{"relation_type": "string or none", "strength": 0.0-1.0, "explanation": "string"}}

## ЗОНА A (стр. {page_a}, {form_a})
{content_a}

## ЗОНА B (стр. {page_b}, {form_b})
{content_b}"""

    def __init__(self):
        self.edges: list[dict] = []
        self._entity_index: dict[str, list[str]] = defaultdict(list)

    def _extract_entities(self, content: str) -> list[str]:
        """Извлекает именованные сущности из текста зоны."""
        entities = []
        # Ищем слова с заглавной буквы (2+ слов)
        for match in re.finditer(r'\b[А-ЯA-Z][а-яa-z]+(?:\s+[А-ЯA-Z][а-яa-z]+){0,4}', content):
            entity = match.group().strip()
            if len(entity) > 5:
                entities.append(entity)
        return list(set(entities))[:10]

    def build_index(self, zone_store: ZoneStore):
        """Строит индекс сущностей по всем зонам."""
        print("  CrossPageLinker: building entity index...")
        for uri, zone in zone_store.zones.items():
            entities = self._extract_entities(zone.content)
            for entity in entities:
                self._entity_index[entity].append(uri)

        unique_entities = len(self._entity_index)
        total_refs = sum(len(v) for v in self._entity_index.values())
        print(f"  CrossPageLinker: {unique_entities} unique entities, {total_refs} references")

    def find_connections(self, zone_store: ZoneStore, max_pairs: int = 100) -> list[dict]:
        """Находит связи между зонами через общие сущности."""
        self.build_index(zone_store)

        # Находим пары зон с общими сущностями
        pairs = set()
        for entity, uris in self._entity_index.items():
            if len(uris) < 2:
                continue
            for i in range(len(uris)):
                for j in range(i + 1, len(uris)):
                    zone_a = zone_store.zones[uris[i]]
                    zone_b = zone_store.zones[uris[j]]
                    if zone_a.page_id != zone_b.page_id:  # только разные страницы
                        pair = tuple(sorted([uris[i], uris[j]]))
                        pairs.add((pair, entity))

        pairs_list = list(pairs)[:max_pairs]
        print(f"  CrossPageLinker: {len(pairs_list)} potential connections")

        t0 = time.time()
        edges_found = 0

        for (uri_a, uri_b), shared_entity in pairs_list[:50]:  # лимит для скорости
            zone_a = zone_store.zones[uri_a]
            zone_b = zone_store.zones[uri_b]

            # Быстрая проверка: если разные формы — выше вероятность связи
            prompt = self.VERIFY_PROMPT.format(
                page_a=zone_a.page_id, form_a=zone_a.form, content_a=zone_a.content[:1000],
                page_b=zone_b.page_id, form_b=zone_b.form, content_b=zone_b.content[:1000],
            )
            result = _parse_json(_call_ollama(prompt, max_tokens=256))

            rel_type = result.get("relation_type")
            if rel_type and rel_type != "none":
                strength = result.get("strength", 0.5)
                if strength > 0.3:
                    edge = {
                        "source_zone": uri_a,
                        "target_zone": uri_b,
                        "source_page": zone_a.page_id,
                        "target_page": zone_b.page_id,
                        "relation_type": rel_type,
                        "strength": strength,
                        "shared_entity": shared_entity,
                        "explanation": result.get("explanation", ""),
                    }
                    self.edges.append(edge)
                    edges_found += 1

        elapsed = time.time() - t0
        print(f"  CrossPageLinker: {edges_found} edges verified — {elapsed:.1f}s")
        return self.edges

    def get_path(self, page_a: int, page_b: int) -> list[dict] | None:
        """Находит путь между двумя страницами в графе."""
        # Строим adjacency list
        adj = defaultdict(list)
        for edge in self.edges:
            adj[edge["source_page"]].append(edge)
            adj[edge["target_page"]].append(edge)

        # BFS
        from collections import deque
        visited = {page_a}
        queue = deque([(page_a, [])])

        while queue:
            current, path = queue.popleft()
            if current == page_b:
                return path

            for edge in adj[current]:
                neighbor = edge["target_page"] if edge["source_page"] == current else edge["source_page"]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [edge]))

        return None

    def to_dict(self) -> dict:
        return {
            "edges": self.edges,
            "total_edges": len(self.edges),
            "pages_connected": len(set(
                e["source_page"] for e in self.edges
            ) | set(
                e["target_page"] for e in self.edges
            )),
        }