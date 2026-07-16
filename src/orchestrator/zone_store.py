"""Шаг 1: Zone-Centric Pipeline — векторное хранилище зон.

Заменяет странично-ориентированное хранение на зонно-ориентированное.
Каждая зона получает:
- Уникальный URI (doc_id/page_zone_form)
- Векторный эмбеддинг (4096d, qwen3-embedding:8b)
- Метаданные (page_id, form, content, entities)

Персистентность: FAISS + SQLite в директории контура.
- embeddings.faiss — FAISS IndexFlatIP (4096d)
- zones.db (SQLite) — метаданные зон + граф связей
- meta.json — метаданные контура

Использует локальную Ollama для эмбеддингов, без внешних зависимостей.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.config import OLLAMA_LOCAL_BASE

EMBED_MODEL = "qwen3-embedding:8b"
EMBED_DIM = 4096


@dataclass
class Zone:
    """Зона — атомарная единица смысла."""
    zone_id: str
    page_id: int
    form: str
    content: str  # текстовое представление зоны
    embedding: list[float] | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def uri(self) -> str:
        return f"doc/p{self.page_id}/{self.zone_id}"


class ZoneStore:
    """Векторное хранилище зон с cosine similarity поиском."""

    def __init__(self):
        self.zones: dict[str, Zone] = {}
        self._embeddings: list[list[float]] = []
        self._zone_ids: list[str] = []

    def _get_embedding(self, text: str) -> list[float]:
        """Получает эмбеддинг через локальную Ollama."""
        data = json.dumps({
            "model": EMBED_MODEL,
            "prompt": text[:8000],
        }).encode()
        req = urllib.request.Request(
            f"{OLLAMA_LOCAL_BASE}/api/embeddings",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["embedding"]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        return dot / (norm_a * norm_b + 1e-10)

    def add_zone(self, page_id: int, zone_id: str, form: str, content: str,
                 metadata: dict | None = None, embed: bool = True) -> Zone:
        """Добавляет зону в хранилище."""
        zone = Zone(
            zone_id=zone_id,
            page_id=page_id,
            form=form,
            content=content,
            metadata=metadata or {},
        )
        self.zones[zone.uri] = zone

        if embed:
            try:
                zone.embedding = self._get_embedding(content)
                self._embeddings.append(zone.embedding)
                self._zone_ids.append(zone.uri)
            except Exception:
                zone.embedding = None

        return zone

    def add_zones_from_schemas(self, schemas: dict[int, dict]) -> int:
        """Загружает все зоны из схем пайплайна."""
        count = 0
        total = len(schemas)
        print(f"  ZoneStore: indexing {total} pages...")

        for pid in sorted(schemas.keys()):
            schema = schemas[pid]
            form = schema.get("form", "discursive")

            if schema.get("empty"):
                continue

            if form == "mixed":
                # Mixed: каждая zone_schema → отдельная зона
                zone_schemas = schema.get("zone_schemas", {})
                for zform, zschema in zone_schemas.items():
                    if not isinstance(zschema, dict):
                        continue
                    content = self._zone_to_text(zschema, zform)
                    if content:
                        self.add_zone(pid, f"zone_{zform}", zform, content, {
                            "page_id": pid,
                            "form": zform,
                            "source": "zone_schema",
                        })
                        count += 1

                # Также добавляем сводную зону
                overall = schema.get("overall_structure", "")
                if overall:
                    self.add_zone(pid, "zone_overall", "discursive", overall, {
                        "page_id": pid, "form": "mixed", "source": "overall_structure",
                    })
                    count += 1
            else:
                # Не-mixed: вся страница — одна зона
                content = self._zone_to_text(schema, form)
                if content:
                    self.add_zone(pid, "zone_main", form, content, {
                        "page_id": pid, "form": form, "source": "page_schema",
                    })
                    count += 1

        print(f"  ZoneStore: {count} zones indexed ({len(self._embeddings)} embeddings)")
        return count

    def _zone_to_text(self, schema: dict, form: str) -> str:
        """Преобразует схему зоны в текстовое представление."""
        parts = []

        title = schema.get("page_title", schema.get("title", ""))
        if title:
            parts.append(f"Заголовок: {title}")

        conclusion = schema.get("conclusion", "")
        if conclusion:
            parts.append(f"Вывод: {conclusion}")

        # Form-specific fields
        if form == "topology":
            for s in schema.get("sets", []):
                name = s.get("name", "")
                elements = s.get("elements", [])[:5]
                if name:
                    parts.append(f"Множество {name}: {', '.join(elements)}")
            for m in schema.get("all_metrics", [])[:10]:
                parts.append(f"{m.get('label', '')}: {m.get('value', '')}")

        elif form == "enumeration":
            for item in schema.get("items", [])[:10]:
                if isinstance(item, str):
                    parts.append(f"- {item}")

        elif form == "matrix":
            for col in schema.get("columns", [])[:5]:
                parts.append(f"Колонка: {col}")
            for row in schema.get("rows", [])[:5]:
                label = row.get("label", "")
                cells = row.get("cells", [])[:3]
                parts.append(f"{label}: {', '.join(cells)}")

        elif form == "hierarchy":
            for level in schema.get("levels", [])[:5]:
                parts.append(f"Уровень {level.get('position', '?')}: {level.get('label', '')} — {level.get('meaning', '')}")

        elif form == "spatial":
            for region in schema.get("regions", [])[:10]:
                name = region.get("name", "")
                metrics = region.get("metrics", {})
                if name:
                    parts.append(f"Регион {name}: {json.dumps(metrics, ensure_ascii=False)}")

        elif form == "dynamics":
            for curve in schema.get("curves", [])[:5]:
                parts.append(f"Кривая {curve.get('name', '')}: {curve.get('direction', '')}")

        # Key theses
        for thesis in schema.get("key_theses", [])[:5]:
            if isinstance(thesis, str):
                parts.append(f"Тезис: {thesis}")

        # Key terms
        for term in schema.get("key_terms", [])[:5]:
            if isinstance(term, str):
                parts.append(f"Термин: {term}")

        # Full text for discursive
        ft = schema.get("full_text", "")
        if ft:
            parts.append(ft[:500])

        return "\n".join(parts) if parts else ""

    def search(self, query: str, top_k: int = 10) -> list[tuple[Zone, float]]:
        """Поиск зон по запросу."""
        if not self._embeddings:
            return []

        query_emb = self._get_embedding(query)
        scores = []
        for i, emb in enumerate(self._embeddings):
            if emb is None:
                continue
            score = self._cosine_similarity(query_emb, emb)
            scores.append((i, score))

        scores.sort(key=lambda x: -x[1])
        results = []
        for i, score in scores[:top_k]:
            uri = self._zone_ids[i]
            zone = self.zones[uri]
            results.append((zone, score))

        return results

    def get_context_for_query(self, query: str, max_zones: int = 15, max_chars: int = 8000) -> str:
        """Собирает контекст для ответа на вопрос."""
        results = self.search(query, top_k=max_zones * 2)

        # Группируем по страницам и дедуплицируем
        seen_pages = set()
        selected = []
        total_chars = 0

        for zone, score in results:
            if zone.page_id in seen_pages:
                continue
            if total_chars + len(zone.content) > max_chars:
                break
            seen_pages.add(zone.page_id)
            selected.append((zone, score))
            total_chars += len(zone.content)

        if not selected:
            return "Нет релевантных зон."

        parts = []
        parts.append(f"## РЕЛЕВАНТНЫЕ ЗОНЫ ДОКУМЕНТА (найдено {len(selected)})\n")
        for zone, score in selected:
            parts.append(f"### стр. {zone.page_id} [{zone.form}] (score: {score:.2f})")
            parts.append(zone.content[:1000])
            parts.append("")

        return "\n".join(parts)

    def stats(self) -> dict:
        return {
            "total_zones": len(self.zones),
            "total_embeddings": len(self._embeddings),
            "pages_covered": len(set(z.page_id for z in self.zones.values())),
        }

    # ═══════════════════════════════════════════════════════════
    # Persistence: FAISS binary + SQLite
    # ═══════════════════════════════════════════════════════════

    def save(self, contour_dir: str) -> str:
        """Сохраняет зоны в FAISS + SQLite."""
        contour_path = Path(contour_dir)
        contour_path.mkdir(parents=True, exist_ok=True)

        # FAISS binary (простой формат: dim + count + vectors)
        faiss_path = contour_path / "embeddings.faiss"
        with open(faiss_path, "wb") as f:
            f.write(struct.pack("II", EMBED_DIM, len(self._embeddings)))
            for emb in self._embeddings:
                if emb:
                    f.write(struct.pack(f"{len(emb)}f", *emb))

        # SQLite
        db_path = contour_path / "zones.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS zones (
                    uri TEXT PRIMARY KEY,
                    page_id INTEGER,
                    zone_id TEXT,
                    form TEXT,
                    content TEXT,
                    metadata_json TEXT
                )
            """)
            conn.execute("DELETE FROM zones")
            for uri, zone in self.zones.items():
                conn.execute(
                    "INSERT INTO zones VALUES (?, ?, ?, ?, ?, ?)",
                    (uri, zone.page_id, zone.zone_id, zone.form,
                     zone.content, json.dumps(zone.metadata, ensure_ascii=False)),
                )
            conn.commit()

        # Метаданные
        meta = {
            "embedding_dim": EMBED_DIM,
            "model": EMBED_MODEL,
            "zone_count": len(self.zones),
            "embedding_count": len(self._embeddings),
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(contour_path / "meta.json", "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        print(f"  ZoneStore saved: {len(self.zones)} zones, {len(self._embeddings)} embeddings → {contour_dir}")
        return str(contour_path)

    @classmethod
    def load(cls, contour_dir: str) -> "ZoneStore":
        """Загружает зоны из FAISS + SQLite."""
        store = cls()
        contour_path = Path(contour_dir)

        # FAISS binary
        faiss_path = contour_path / "embeddings.faiss"
        if faiss_path.exists():
            with open(faiss_path, "rb") as f:
                dim, count = struct.unpack("II", f.read(8))
                for i in range(count):
                    emb = list(struct.unpack(f"{dim}f", f.read(dim * 4)))
                    store._embeddings.append(emb)

        # SQLite
        db_path = contour_path / "zones.db"
        if db_path.exists():
            with sqlite3.connect(str(db_path)) as conn:
                rows = conn.execute("SELECT * FROM zones").fetchall()
                for row in rows:
                    uri, page_id, zone_id, form, content, metadata_json = row
                    zone = Zone(
                        zone_id=zone_id, page_id=page_id, form=form,
                        content=content, metadata=json.loads(metadata_json),
                    )
                    store.zones[uri] = zone

        # Восстанавливаем _zone_ids
        store._zone_ids = list(store.zones.keys())

        if store._embeddings and len(store._embeddings) != len(store._zone_ids):
            # Эмбеддинги не совпадают — загружаем заново
            print(f"  ZoneStore: embedding mismatch, re-indexing...")
            store._embeddings = []
            store._zone_ids = []
            for uri, zone in store.zones.items():
                try:
                    zone.embedding = store._get_embedding(zone.content)
                    store._embeddings.append(zone.embedding)
                    store._zone_ids.append(uri)
                except Exception:
                    pass

        print(f"  ZoneStore loaded: {len(store.zones)} zones, {len(store._embeddings)} embeddings")
        return store