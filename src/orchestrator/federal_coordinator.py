"""Federal Coordinator — мультифедеративный поиск по контурам.

Архитектура:
  FederalCoordinator
    ├── Registry (SQLite)     — каталог контуров, метаданные
    ├── Router                — выбор контуров-кандидатов
    ├── Aggregator (RRF)      — слияние результатов
    └── Reranker (heuristic)  — переранжирование

Принципы:
- Координатор НЕ хранит векторы контуров — только метаданные и scores
- Каждый контур суверенен: FAISS + SQLite в своей директории
- Коммуникация: Python multiprocessing (air-gap, без сети)
- RRF-слияние не требует калибровки метрик разных моделей
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

STORE_ROOT = Path.home() / ".qwen" / "ai-canvas" / "contours"


@dataclass
class CircuitMeta:
    """Метаданные контура."""
    circuit_id: str
    name: str
    path: str
    embedding_dim: int = 4096
    model_hash: str = ""
    zone_count: int = 0
    edge_count: int = 0
    domains: list[str] = field(default_factory=list)
    status: str = "active"  # active | indexing | locked
    version: int = 1
    created_at: str = ""
    last_indexed: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class SearchResult:
    """Результат поиска из одного контура."""
    circuit_id: str
    zone_id: str
    page_id: int
    score: float
    content_preview: str
    metadata: dict = field(default_factory=dict)


class Registry:
    """SQLite-каталог контуров."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            STORE_ROOT.mkdir(parents=True, exist_ok=True)
            db_path = str(STORE_ROOT / "registry.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS circuits (
                    circuit_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    embedding_dim INTEGER DEFAULT 4096,
                    model_hash TEXT DEFAULT '',
                    zone_count INTEGER DEFAULT 0,
                    edge_count INTEGER DEFAULT 0,
                    domains TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'active',
                    version INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT '',
                    last_indexed TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS circuits_fts
                USING fts5(circuit_id, name, domains, content='circuits', content_rowid='rowid')
            """)
            conn.commit()

    def register(self, meta: CircuitMeta):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO circuits
                (circuit_id, name, path, embedding_dim, model_hash, zone_count, edge_count,
                 domains, status, version, created_at, last_indexed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                meta.circuit_id, meta.name, meta.path, meta.embedding_dim,
                meta.model_hash, meta.zone_count, meta.edge_count,
                json.dumps(meta.domains), meta.status, meta.version,
                meta.created_at, meta.last_indexed,
            ))
            conn.commit()

    def get(self, circuit_id: str) -> CircuitMeta | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM circuits WHERE circuit_id = ?", (circuit_id,)
            ).fetchone()
            if row:
                return CircuitMeta(
                    circuit_id=row["circuit_id"], name=row["name"], path=row["path"],
                    embedding_dim=row["embedding_dim"], model_hash=row["model_hash"],
                    zone_count=row["zone_count"], edge_count=row["edge_count"],
                    domains=json.loads(row["domains"]), status=row["status"],
                    version=row["version"], created_at=row["created_at"],
                    last_indexed=row["last_indexed"],
                )
        return None

    def list_active(self) -> list[CircuitMeta]:
        metas = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM circuits WHERE status = 'active' ORDER BY created_at DESC"
            ).fetchall()
            for row in rows:
                metas.append(CircuitMeta(
                    circuit_id=row["circuit_id"], name=row["name"], path=row["path"],
                    embedding_dim=row["embedding_dim"], model_hash=row["model_hash"],
                    zone_count=row["zone_count"], edge_count=row["edge_count"],
                    domains=json.loads(row["domains"]), status=row["status"],
                    version=row["version"], created_at=row["created_at"],
                    last_indexed=row["last_indexed"],
                ))
        return metas

    def search_circuits(self, query: str, top_k: int = 10) -> list[CircuitMeta]:
        """FTS5-поиск по имени и доменам контуров."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT circuit_id FROM circuits_fts WHERE circuits_fts MATCH ? LIMIT ?",
                (query, top_k),
            ).fetchall()
            return [m for rid in rows if (m := self.get(rid["circuit_id"]))]


class ReciprocalRankFusion:
    """RRF-слияние результатов из разных контуров.

    RRF = Σ (1 / (k + rank_i))
    где rank_i — позиция документа в выдаче контура, k ≈ 60.
    """

    def __init__(self, k: int = 60):
        self.k = k

    def merge(self, results_by_circuit: dict[str, list[SearchResult]], top_n: int = 50) -> list[SearchResult]:
        """Сливает результаты из разных контуров через RRF."""
        scores: dict[str, float] = defaultdict(float)
        doc_map: dict[str, SearchResult] = {}

        for circuit_id, results in results_by_circuit.items():
            for rank, result in enumerate(results):
                key = f"{circuit_id}:{result.zone_id}"
                scores[key] += 1.0 / (self.k + rank + 1)
                if key not in doc_map:
                    doc_map[key] = result

        # Сортируем по RRF-скор
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        merged = []
        for key, score in ranked[:top_n]:
            doc = doc_map[key]
            doc.score = score
            merged.append(doc)

        return merged


class HeuristicReranker:
    """Эвристический переранжировщик (без ONNX).

    Переранжирует top-N результатов через:
    - TF-IDF overlap query vs content
    - Semantic affinity (cosine similarity через эмбеддинги)
    - Circuit affinity weight
    """

    def __init__(self, embed_model: str = "qwen3-embedding:8b"):
        self.embed_model = embed_model
        self._circuit_affinity: dict[str, float] = {}

    def set_circuit_affinity(self, circuit_id: str, weight: float):
        self._circuit_affinity[circuit_id] = weight

    def _tf_idf_overlap(self, query: str, content: str) -> float:
        query_terms = set(query.lower().split())
        content_terms = set(content.lower().split())
        if not query_terms:
            return 0.0
        return len(query_terms & content_terms) / len(query_terms)

    def rerank(self, query: str, results: list[SearchResult], top_n: int = 20) -> list[SearchResult]:
        """Переранжирует результаты."""
        for r in results:
            tfidf = self._tf_idf_overlap(query, r.content_preview)
            affinity = self._circuit_affinity.get(r.circuit_id, 0.5)
            # Комбинированный скор: RRF + TF-IDF + affinity
            r.score = 0.5 * r.score + 0.3 * tfidf + 0.2 * affinity

        results.sort(key=lambda r: -r.score)
        return results[:top_n]


class FederalCoordinator:
    """Федеративный координатор поиска по контурам."""

    def __init__(self, db_path: str | None = None):
        self.registry = Registry(db_path)
        self.rrf = ReciprocalRankFusion(k=60)
        self.reranker = HeuristicReranker()
        self._circuit_stores: dict[str, object] = {}  # кэш ZoneStore

    def register_circuit(self, name: str, path: str, zone_count: int = 0,
                         edge_count: int = 0, domains: list[str] | None = None) -> CircuitMeta:
        """Регистрирует новый контур."""
        meta = CircuitMeta(
            circuit_id=f"circuit_{uuid.uuid4().hex[:8]}",
            name=name,
            path=path,
            zone_count=zone_count,
            edge_count=edge_count,
            domains=domains or [],
        )
        self.registry.register(meta)
        return meta

    def list_circuits(self) -> list[CircuitMeta]:
        return self.registry.list_active()

    def _search_circuit(self, circuit_meta: CircuitMeta, query_embedding: list[float],
                        top_k: int = 30) -> list[SearchResult]:
        """Поиск в одном контуре."""
        from src.orchestrator.zone_store import ZoneStore

        cid = circuit_meta.circuit_id
        if cid not in self._circuit_stores:
            # Загружаем из FAISS+SQLite (если есть) или из schemas.json
            contour_path = Path(circuit_meta.path)
            if (contour_path / "embeddings.faiss").exists():
                self._circuit_stores[cid] = ZoneStore.load(str(contour_path))
            elif (contour_path / "03_schemas.json").exists():
                store = ZoneStore()
                with open(contour_path / "03_schemas.json") as f:
                    schemas_raw = json.load(f)
                schemas = {int(k): v for k, v in schemas_raw.items()} if isinstance(schemas_raw, dict) else {
                    s["page_id"]: s for s in schemas_raw
                }
                store.add_zones_from_schemas(schemas)
                self._circuit_stores[cid] = store
            else:
                return []

        store = self._circuit_stores[cid]
        if not store._embeddings:
            return []

        results = []
        for i, emb in enumerate(store._embeddings):
            if emb is None:
                continue
            score = store._cosine_similarity(query_embedding, emb)
            if score > 0.3:  # порог
                uri = store._zone_ids[i]
                zone = store.zones[uri]
                results.append(SearchResult(
                    circuit_id=cid,
                    zone_id=zone.zone_id,
                    page_id=zone.page_id,
                    score=score,
                    content_preview=zone.content[:200],
                    metadata={"form": zone.form, "circuit_name": circuit_meta.name},
                ))

        results.sort(key=lambda r: -r.score)
        return results[:top_k]

    def search(self, query: str, query_embedding: list[float] | None = None,
               circuit_ids: list[str] | None = None, top_k: int = 30) -> list[SearchResult]:
        """Федеративный поиск по всем активным контурам."""
        t0 = time.time()

        # Выбираем контуры
        if circuit_ids:
            circuits = [self.registry.get(cid) for cid in circuit_ids]
            circuits = [c for c in circuits if c and c.status == "active"]
        else:
            circuits = self.registry.list_active()

        if not circuits:
            return []

        # Получаем эмбеддинг запроса
        if query_embedding is None:
            from src.orchestrator.zone_store import ZoneStore
            store = ZoneStore()
            query_embedding = store._get_embedding(query)

        print(f"  FederalCoordinator: searching {len(circuits)} circuits for '{query[:60]}...'")

        # Параллельный поиск по контурам
        results_by_circuit: dict[str, list[SearchResult]] = {}
        with ThreadPoolExecutor(max_workers=min(len(circuits), 8)) as executor:
            futures = {
                executor.submit(self._search_circuit, c, query_embedding, top_k): c.circuit_id
                for c in circuits
            }
            for future in as_completed(futures):
                cid = futures[future]
                try:
                    results_by_circuit[cid] = future.result()
                except Exception as e:
                    print(f"    Circuit {cid}: error — {e}")

        # RRF-слияние
        merged = self.rrf.merge(results_by_circuit, top_n=top_k * 2)

        # Переранжирование
        reranked = self.reranker.rerank(query, merged, top_n=top_k)

        elapsed = time.time() - t0
        total_hits = sum(len(v) for v in results_by_circuit.values())
        print(f"  FederalCoordinator: {total_hits} hits → {len(merged)} merged → {len(reranked)} reranked — {elapsed:.1f}s")

        return reranked

    def get_context(self, query: str, query_embedding: list[float] | None = None,
                    max_zones: int = 15, max_chars: int = 8000) -> str:
        """Собирает контекст из федеративного поиска."""
        results = self.search(query, query_embedding, top_k=max_zones * 2)

        # Группируем по контурам и страницам
        seen = set()
        selected = []
        total_chars = 0

        for r in results:
            key = f"{r.circuit_id}:{r.page_id}"
            if key in seen:
                continue
            if total_chars + len(r.content_preview) > max_chars:
                break
            seen.add(key)
            selected.append(r)
            total_chars += len(r.content_preview)

        if not selected:
            return "Нет релевантных результатов."

        parts = [f"## ФЕДЕРАТИВНЫЙ ПОИСК ({len(selected)} зон из {len(set(r.circuit_id for r in selected))} контуров)\n"]
        for r in selected:
            parts.append(f"### [{r.metadata.get('circuit_name', '?')}] стр. {r.page_id} [{r.metadata.get('form', '?')}] (score: {r.score:.3f})")
            parts.append(r.content_preview[:800])
            parts.append("")

        return "\n".join(parts)

    def stats(self) -> dict:
        circuits = self.registry.list_active()
        return {
            "total_circuits": len(circuits),
            "total_zones": sum(c.zone_count for c in circuits),
            "total_edges": sum(c.edge_count for c in circuits),
            "circuits": [
                {"id": c.circuit_id, "name": c.name, "zones": c.zone_count, "status": c.status}
                for c in circuits
            ],
        }