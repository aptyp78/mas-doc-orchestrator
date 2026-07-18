# AI Canvas — Agent Context

## Project Identity

**AI Canvas** — sovereign C-level analysis and assistance environment. Zero-shot heterogeneous PDF parsing into federated vector-graph knowledge. On-premise, air-gap capable.

**Target user:** CEO/CTO/CIO — non-technical. Interface: natural language only.

**Mission:** восстановить деятельность, породившую документ — не «извлечь данные», а понять, кто, зачем и в какой оргструктуре его создал. Смысл не извлекается из текста — он находится в системе деятельности вне документа.

**Методология:** СМД Г.П. Щедровицкого (Activity Theory + операционно-ролевые позиции).

## Mandatory Reading

1. `docs/CONSTITUTION.md` — 6 principles, architecture constraints, v1 criteria
2. `docs/adr/003-constitution-roles.md` — 7 ОРП, конституция v2.2
3. `docs/adr/004-vector-graph-store.md` — FAISS+SQLite, федеративные контуры
4. `docs/verdicts/001-deepseek-ocr2.md` — вердикт по OCR2
5. `HANDOFF.md` — точка входа для нового агента
6. `QWEN.md` — основной контекст (архитектура, протокол, модули)

## Architecture

```
                   ┌──────────────────────────────┐
                   │     C-level Manager           │
                   └──────────────┬───────────────┘
                                  │
                   ┌──────────────┴───────────────┐
                   │      Qwen Code Agent          │
                   │   (ask_orchestrator.py)        │
                   └──────────────┬───────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ OCR2 Pipeline   │   │ SMD Core (FSM)  │   │ Federal Layer   │
│ (ocr2_norm)     │   │ (orchestrator/) │   │ (zone_store,    │
│                 │   │                 │   │  federal_coord) │
└─────────────────┘   └─────────────────┘   └─────────────────┘

Pipeline:
  L0: ocr2_normalizer  → DeepSeek OCR2 (1-3s/page, local MLX)
  L1: classifier       → 7 SMD sign forms (block-based)
  L2: extractors       → schema extraction (text, table, image)
  L3: ontology         → domain ontology mapper
  L4: reflector        → C-level recommendations

Orchestrator (6 modules):
  provenance.py            → SHA-256 traceability chain
  htr_loop.py              → Hypothesis-Test-Revisit cycle
  cross_page_synthesizer.py → Cross-page semantic graph
  cross_page_linker.py     → Entity-based cross-page connections
  doubt_gate.py            → Confidence gate + unknown zones
  dialogue_mediator.py     → Advocate/Skeptic/Synthesizer
  smd_core.py              → FSM: Exploration→Synthesis→Doubt→Dialogue→Verification

Data Layer:
  zone_store.py         → 4096d embeddings, FAISS+SQLite persistence
  federal_coordinator.py → Multi-circuit federated search (RRF)
  store.py              → VectorGraphStore (FAISS + SQLite)
```

## Module Map

```
src/
├── semiotic/          8 files  — L1-L4 pipeline + Cloud variants
├── orchestrator/     14 files  — orchestration core + roles + federal
├── normalizer/        3 files  — ocr2, pdf_normalizer, vl_normalizer
├── agents/            3 files  — dashscope, ollama_local, brave
├── store.py                     — VectorGraphStore (FAISS+SQLite)
├── confidence_guard.py          — stagnation/divergence/overfitting
└── utils/config.py              — LazyKey: keychain → env fallback

scripts/
├── run_ocr2_pipeline.py         — NEW: OCR2-based pipeline (local)
├── run_cloud_pipeline.py        — Cloud pipeline (DashScope)
├── ask_orchestrator.py          — C-level Q&A dispatcher
├── generate_dashboard.py        — HTML dashboard generator
├── generate_recommendations.py  — Single-request C-level recs
├── generate_ontology_reflection.py — Per-page ontology+reflection
└── ...

prompts/               — 14 versioned .md prompts (CHANGELOG + AUDIT)
docs/
├── CONSTITUTION.md
├── architecture.md
├── adr/               — 4 ADRs + 7 role specs
└── verdicts/          — technology adoption verdicts
```

## Conventions

### Communication
- **Russian** for all communication with the user and within the project
- **English** for code: identifiers, docstrings, commit messages

### Code
- Python 3.12+, static typing (mypy compatible)
- `ruff` for linting, line length 120
- **Роли не вызывают другие роли.** Координация — только через Dispatcher.
- **Промпты — роли, не инструкции.** Формат: `[РОЛЬ]...[ОГРАНИЧЕНИЕ]`.
- **SEMANTIC_GAP — правильный ответ.** Отправляй в Context Resolver.
- `make lint` перед коммитом.

### C-Level answers
- **Всегда с provenance.** Никаких утверждений без ссылки на страницу.
- **Всегда с doubt_gate.** Если confidence < 0.65 — честно предупреди.
- **Всегда multi-position.** Для стратегических вопросов — advocate/skeptic/synthesizer.
- **Не выдумывай.** Если данных нет — скажи «недостаточно данных».

## Quick Start

```bash
# Full pipeline (OCR2, local)
python3 scripts/run_ocr2_pipeline.py data/docs/Презентация_ИАфр_РАН_финал.pdf

# Ask a question
python3 scripts/ask_orchestrator.py "Какие риски для России в Африке?"

# Generate dashboard
python3 scripts/generate_dashboard.py output/run_ocr2_*/

# Federal multi-circuit search
python3 -c "
from src.orchestrator.federal_coordinator import FederalCoordinator
fc = FederalCoordinator()
fc.register_circuit('doc1', 'output/run_1/')
fc.register_circuit('doc2', 'output/run_2/')
print(fc.search('минеральные ресурсы'))
"
```

## Repository Rules (HARD)

1. **Never commit to master directly.** Feature branch → PR.
2. **Only aptyp78 merges.** All PRs require aptyp78 approval.
3. **PR checklist:** tests pass, lint passes, constitution compliance.
4. **One PR = one concern.**
5. **Commit messages in English**, imperative mood.

## Dependencies

- **Local LLM:** Ollama — qwen3-vl:30b (vision), qwen3.6:35b (reasoning/SMD), qwen3-embedding:8b (4096d)
- **OCR:** DeepSeek OCR2 (MLX, Apple Silicon) — replaces Tesseract + Cloud vision
- **Cloud (dev):** DashScope, Ollama Cloud — only when network available
- **Python:** pymupdf, pdfplumber, Pillow, requests
- **Dev:** pytest, ruff, mypy