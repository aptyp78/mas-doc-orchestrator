"""Vector-Graph Store: суверенное векторно-графовое хранилище.

Архитектура:
  ~/.qwen/ai-canvas/contours/<name>/
    ├── graph.db         — SQLite (узлы + рёбра)
    ├── embeddings.faiss — FAISS index
    └── meta.json        — метаданные контура

Поиск:
  - Семантический: embedding → FAISS cosine similarity
  - Структурный: SQL → graph traversal
  - Гибридный: оба + rerank
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

# FAISS — опциональный импорт (может не быть установлен)
try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

OLLAMA_BASE = "http://localhost:11434"
STORE_ROOT = Path.home() / ".qwen" / "ai-canvas" / "contours"


class VectorGraphStore:
    """Суверенное векторно-графовое хранилище.

    Каждый контур — отдельная директория с SQLite + FAISS.
    """

    def __init__(self, contour: str, embedding_dim: int = 4096):
        self.contour = contour
        self.embedding_dim = embedding_dim
        self.contour_dir = STORE_ROOT / contour
        self.contour_dir.mkdir(parents=True, exist_ok=True)

        # SQLite
        self.db_path = self.contour_dir / "graph.db"
        self._init_db()

        # FAISS
        self.faiss_path = str(self.contour_dir / "embeddings.faiss")
        self._init_faiss()

        # Метаданные
        self.meta_path = self.contour_dir / "meta.json"
        self._init_meta()

    # ═══════════════════════════════════════════════════════════
    # Init
    # ═══════════════════════════════════════════════════════════

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                type TEXT DEFAULT 'entity',
                properties TEXT DEFAULT '{}',
                embedding_id INTEGER,  -- FAISS index
                created_at REAL,
                updated_at REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                type TEXT DEFAULT 'references',
                properties TEXT DEFAULT '{}',
                FOREIGN KEY(source_id) REFERENCES nodes(id),
                FOREIGN KEY(target_id) REFERENCES nodes(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)")
        conn.commit()
        conn.close()

    def _init_faiss(self):
        if not HAS_FAISS:
            self.faiss_index = None
            return
        if os.path.exists(self.faiss_path):
            self.faiss_index = faiss.read_index(self.faiss_path)
        else:
            self.faiss_index = faiss.IndexFlatIP(self.embedding_dim)  # cosine = inner product after norm

    def _init_meta(self):
        if not self.meta_path.exists():
            with open(self.meta_path, "w") as f:
                json.dump({
                    "contour": self.contour,
                    "created_at": time.time(),
                    "embedding_dim": self.embedding_dim,
                    "node_count": 0,
                    "edge_count": 0,
                }, f, indent=2)

    # ═══════════════════════════════════════════════════════════
    # Write
    # ═══════════════════════════════════════════════════════════

    def add_node(
        self, label: str, node_type: str = "entity",
        properties: dict | None = None, embedding: list[float] | None = None,
    ) -> str:
        node_id = str(uuid.uuid4())
        now = time.time()
        props = json.dumps(properties or {}, ensure_ascii=False)

        embedding_id = None
        if embedding is not None and HAS_FAISS and self.faiss_index is not None:
            vec = np.array(embedding, dtype=np.float32).reshape(1, -1)
            # Нормализация для cosine similarity
            faiss.normalize_L2(vec)
            embedding_id = self.faiss_index.ntotal
            self.faiss_index.add(vec)

        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node_id, label, node_type, props, embedding_id, now, now),
        )
        conn.commit()
        conn.close()

        self._update_meta()
        return node_id

    def add_edge(
        self, source_id: str, target_id: str,
        edge_type: str = "references", properties: dict | None = None,
    ) -> str:
        edge_id = str(uuid.uuid4())
        props = json.dumps(properties or {}, ensure_ascii=False)

        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT INTO edges VALUES (?, ?, ?, ?, ?)",
            (edge_id, source_id, target_id, edge_type, props),
        )
        conn.commit()
        conn.close()

        self._update_meta()
        return edge_id

    def _update_meta(self):
        if self.meta_path.exists():
            with open(self.meta_path) as f:
                meta = json.load(f)
        else:
            meta = {"contour": self.contour, "created_at": time.time()}

        conn = sqlite3.connect(str(self.db_path))
        meta["node_count"] = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        meta["edge_count"] = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        conn.close()
        meta["updated_at"] = time.time()
        with open(self.meta_path, "w") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    def _save_faiss(self):
        if HAS_FAISS and self.faiss_index is not None:
            faiss.write_index(self.faiss_index, self.faiss_path)

    # ═══════════════════════════════════════════════════════════
    # Embedding
    # ═══════════════════════════════════════════════════════════

    def embed(self, text: str) -> list[float]:
        """Получает эмбеддинг через qwen3-embedding:8b с retry."""
        import urllib.request

        data = json.dumps({
            "model": "qwen3-embedding:8b",
            "prompt": text,
        }).encode()

        last_error = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    f"{OLLAMA_BASE}/api/embeddings",
                    data=data, headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = json.loads(resp.read())
                    return raw["embedding"]
            except Exception as e:
                last_error = e
                time.sleep(1.0 * (attempt + 1))

        raise last_error or RuntimeError("embedding failed after 3 retries")

    # ═══════════════════════════════════════════════════════════
    # Search
    # ═══════════════════════════════════════════════════════════

    def search_semantic(self, query: str, k: int = 10) -> list[dict]:
        """Семантический поиск: query → embedding → FAISS."""
        if not HAS_FAISS or self.faiss_index is None or self.faiss_index.ntotal == 0:
            return []

        query_vec = np.array(self.embed(query), dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(query_vec)
        scores, indices = self.faiss_index.search(query_vec, min(k, self.faiss_index.ntotal))

        conn = sqlite3.connect(str(self.db_path))
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            row = conn.execute(
                "SELECT id, label, type, properties FROM nodes WHERE embedding_id = ?",
                (int(idx),),
            ).fetchone()
            if row:
                results.append({
                    "id": row[0], "label": row[1], "type": row[2],
                    "properties": json.loads(row[3]), "score": float(score),
                })
        conn.close()
        return results

    def search_graph(self, node_id: str, hops: int = 2) -> list[dict]:
        """Структурный поиск: graph traversal от узла."""
        conn = sqlite3.connect(str(self.db_path))
        visited = {node_id}
        frontier = {node_id}

        for _ in range(hops):
            next_frontier = set()
            for nid in frontier:
                for row in conn.execute(
                    "SELECT target_id FROM edges WHERE source_id = ?", (nid,)
                ):
                    if row[0] not in visited:
                        next_frontier.add(row[0])
                        visited.add(row[0])
                for row in conn.execute(
                    "SELECT source_id FROM edges WHERE target_id = ?", (nid,)
                ):
                    if row[0] not in visited:
                        next_frontier.add(row[0])
                        visited.add(row[0])
            frontier = next_frontier

        results = []
        for nid in visited:
            row = conn.execute(
                "SELECT id, label, type, properties FROM nodes WHERE id = ?", (nid,)
            ).fetchone()
            if row:
                results.append({
                    "id": row[0], "label": row[1], "type": row[2],
                    "properties": json.loads(row[3]), "distance": 0 if nid == node_id else 1,
                })
        conn.close()
        return results

    def search_hybrid(self, query: str, k: int = 10, hops: int = 1) -> list[dict]:
        """Гибридный поиск: embedding + graph expansion."""
        semantic = self.search_semantic(query, k=k)
        if not semantic:
            return []

        # Graph expansion от top-1 семантического результата
        top_id = semantic[0]["id"]
        graph_results = self.search_graph(top_id, hops=hops)

        # Ранжирование: семантические выше, графовые — дополнение
        seen = {r["id"] for r in semantic}
        combined = list(semantic)
        for r in graph_results:
            if r["id"] not in seen:
                r["score"] = 0.5  # графовые — ниже
                combined.append(r)
                seen.add(r["id"])

        return combined[:k]

    # ═══════════════════════════════════════════════════════════
    # Persistence
    # ═══════════════════════════════════════════════════════════

    def save(self):
        """Сохраняет FAISS индекс на диск."""
        self._save_faiss()

    def close(self):
        """Сохраняет и закрывает."""
        self.save()

    def stats(self) -> dict:
        with open(self.meta_path) as f:
            return json.load(f)