"""Шаг 5: Provenance Backbone — граф неразрывной прослеживаемости.

Каждое C-level утверждение связано с уникальным путём:
  Рекомендация → Аргумент → Онтологическая связка → Схема → Знаковая форма → PDF-координаты

Обеспечивает:
- Хэширование каждого звена цепи (SHA-256)
- Инвалидацию производных выводов при изменении источника
- Верифицируемые цитаты с координатами страниц
- Тип извлечения: явная (explicit) / имплицитная (implicit)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProvenanceNode:
    """Узел цепи provenancе."""
    node_id: str
    level: str  # recommendation, argument, ontology, schema, sign_form, pdf
    content_hash: str
    content_preview: str  # первые 100 символов
    metadata: dict = field(default_factory=dict)
    timestamp: str = ""
    extraction_type: str = "explicit"  # explicit | implicit

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class ProvenanceChain:
    """Цепь provenancе от рекомендации до PDF-координат."""
    chain_id: str
    page_id: int
    nodes: list[ProvenanceNode] = field(default_factory=list)
    created_at: str = ""
    is_valid: bool = True

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def add_node(self, level: str, content: Any, metadata: dict | None = None,
                 extraction_type: str = "explicit") -> ProvenanceNode:
        """Добавляет узел в цепь."""
        content_str = json.dumps(content, ensure_ascii=False, sort_keys=True) if not isinstance(content, str) else content
        content_hash = hashlib.sha256(content_str.encode()).hexdigest()[:16]
        preview = content_str[:100] if isinstance(content_str, str) else str(content)[:100]

        node = ProvenanceNode(
            node_id=f"{self.chain_id}_{level}_{len(self.nodes)}",
            level=level,
            content_hash=content_hash,
            content_preview=preview,
            metadata=metadata or {},
            extraction_type=extraction_type,
        )
        self.nodes.append(node)
        return node

    def validate(self) -> bool:
        """Проверяет целостность цепи."""
        if len(self.nodes) < 2:
            self.is_valid = False
            return False
        # Проверяем, что каждый уровень присутствует
        levels = {n.level for n in self.nodes}
        required = {"sign_form", "schema", "ontology", "recommendation"}
        self.is_valid = required.issubset(levels)
        return self.is_valid

    def to_dict(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "page_id": self.page_id,
            "is_valid": self.is_valid,
            "created_at": self.created_at,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "level": n.level,
                    "content_hash": n.content_hash,
                    "content_preview": n.content_preview,
                    "metadata": n.metadata,
                    "timestamp": n.timestamp,
                    "extraction_type": n.extraction_type,
                }
                for n in self.nodes
            ],
        }

    def trace_path(self) -> str:
        """Возвращает читаемый путь provenancе."""
        path = []
        for n in self.nodes:
            path.append(f"[{n.level}] {n.content_preview}")
        return " → ".join(path)


class ProvenanceMapper:
    """Строит и управляет цепями provenancе для всего документа."""

    def __init__(self):
        self.chains: dict[int, ProvenanceChain] = {}

    def build_chain(
        self,
        page_id: int,
        sign_form: str,
        schema: dict,
        ontology: dict,
        reflection: dict,
        pdf_coords: dict | None = None,
    ) -> ProvenanceChain:
        """Строит полную цепь provenancе для одной страницы."""
        chain_id = f"p{page_id}_{int(time.time())}"
        chain = ProvenanceChain(chain_id=chain_id, page_id=page_id)

        # Уровень 0: PDF-координаты
        if pdf_coords:
            chain.add_node("pdf", pdf_coords, extraction_type="explicit")

        # Уровень 1: Знаковая форма
        chain.add_node("sign_form", sign_form, metadata={
            "page": page_id,
            "form": sign_form,
        })

        # Уровень 2: Схема
        schema_hash = chain.add_node("schema", schema, metadata={
            "form": sign_form,
            "schema_type": schema.get("form", "unknown"),
        })

        # Уровень 3: Онтология
        chain.add_node("ontology", ontology, metadata={
            "entity_count": len(ontology.get("entities", [])),
            "relation_count": len(ontology.get("relations", [])),
        })

        # Уровень 4: Рекомендация
        chain.add_node("recommendation", reflection, metadata={
            "urgency": reflection.get("urgency", "LOW"),
            "confidence": reflection.get("confidence", "LOW"),
        })

        chain.validate()
        self.chains[page_id] = chain
        return chain

    def build_chain_from_pipeline(
        self,
        page_id: int,
        classification: dict,
        schema: dict,
        ontology: dict,
        reflection: dict,
    ) -> ProvenanceChain:
        """Строит цепь из данных пайплайна."""
        form = classification.get("primary_form", "unknown")
        confidence = classification.get("confidence", "LOW")

        return self.build_chain(
            page_id=page_id,
            sign_form=form,
            schema=schema,
            ontology=ontology,
            reflection=reflection,
            pdf_coords={"page": page_id, "confidence": confidence},
        )

    def get_chain(self, page_id: int) -> ProvenanceChain | None:
        return self.chains.get(page_id)

    def get_all_chains(self) -> list[ProvenanceChain]:
        return list(self.chains.values())

    def invalidate_chain(self, page_id: int, reason: str = "") -> ProvenanceChain | None:
        """Инвалидирует цепь (например, при изменении источника)."""
        chain = self.chains.get(page_id)
        if chain:
            chain.is_valid = False
            chain.nodes.append(ProvenanceNode(
                node_id=f"{chain.chain_id}_invalidation",
                level="invalidation",
                content_hash="",
                content_preview=f"Invalidated: {reason}",
                metadata={"reason": reason},
            ))
        return chain

    def to_dict(self) -> dict:
        return {
            "chains": {str(pid): c.to_dict() for pid, c in self.chains.items()},
            "total_chains": len(self.chains),
            "valid_chains": sum(1 for c in self.chains.values() if c.is_valid),
        }

    def export(self) -> dict:
        """Экспорт для дашборда/аудита."""
        return {
            "chains": [
                {
                    "page_id": c.page_id,
                    "is_valid": c.is_valid,
                    "trace": c.trace_path(),
                    "nodes": c.to_dict()["nodes"],
                }
                for c in sorted(self.chains.values(), key=lambda c: c.page_id)
            ],
            "total": len(self.chains),
            "valid": sum(1 for c in self.chains.values() if c.is_valid),
        }