# Векторно-графовое хранилище

**Версия:** 1.0
**Дата:** 2026-07-14
**Принцип:** Суверенность — всё локально, air-gap capable

## Архитектура

```
~/.qwen/ai-canvas/
├── contours/
│   ├── psb/                          # контур «ПСБ»
│   │   ├── graph.db                  # SQLite (узлы + рёбра)
│   │   ├── embeddings.faiss          # FAISS index
│   │   └── meta.json                 # метаданные контура
│   ├── opk/                          # контур «ОПК»
│   │   ├── graph.db
│   │   ├── embeddings.faiss
│   │   └── meta.json
│   └── _cross/                       # межконтурные связи
│       └── edges.json
└── store.lock                        # блокировка на запись
```

## Модель данных

### Узел (Node)
```json
{
  "id": "uuid",
  "contour": "psb",
  "label": "ПСБ как оркестратор ОПК",
  "type": "entity",
  "properties": {
    "source_doc": "ЦОД+ПАК.pdf",
    "source_page": 1,
    "confidence": "HIGH",
    "aliases": ["ПСБ", "Промсвязьбанк"],
    "domain": "банковский"
  },
  "embedding": [0.12, -0.34, ...],  // 512d
  "created_at": "2026-07-14T12:00:00Z",
  "updated_at": "2026-07-14T12:00:00Z"
}
```

### Ребро (Edge)
```json
{
  "id": "uuid",
  "source_id": "node_uuid",
  "target_id": "node_uuid",
  "type": "orchestrates",  // contains, references, regulates, competes_with
  "properties": {
    "source_doc": "ЦОД+ПАК.pdf",
    "confidence": "HIGH"
  }
}
```

## Поиск

### Семантический (векторный)
```
query → embedding → FAISS.search(k=10) → top-k nodes by cosine similarity
```

### Структурный (графовый)
```
query → SQL → найти узлы → graph traversal (1-hop, 2-hop) → connected nodes
```

### Гибридный
```
query → embedding → top-k векторов → graph expansion → rerank → результат
```

## API

```python
from src.store import VectorGraphStore

store = VectorGraphStore(contour="psb")

# Запись
store.add_node(label="ПСБ", type="entity", embedding=[...])
store.add_edge(source_id, target_id, type="orchestrates")

# Поиск
store.search_semantic("суверенная AI инфраструктура", k=10)
store.search_graph(node_id, hops=2)
store.search_hybrid("суверенная AI инфраструктура", k=10, hops=1)
```