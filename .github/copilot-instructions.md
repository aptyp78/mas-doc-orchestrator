# AI Canvas — Copilot Instructions

You are working on **AI Canvas** — sovereign C-level analysis environment. Zero-shot PDF parsing into federated vector-graph knowledge. On-premise, air-gap capable.

## Context
SMD methodology (Г.П. Щедровицкий): 4-level semiotic pipeline (sign form → schema → ontology → C-level recommendation). 6 orchestration modules: provenance (SHA-256), htr_loop, cross_page_synthesizer, doubt_gate, dialogue_mediator, smd_core (FSM). Federal Coordinator for multi-circuit search (RRF). DeepSeek OCR2 as primary normalizer (local MLX, ×28 faster than Cloud).

## Rules
- `make lint` before commit (ruff + mypy)
- Python 3.12+, static typing
- Роли не вызывают другие роли — координация через Dispatcher
- SEMANTIC_GAP — правильный ответ, не галлюцинируй расшифровки
- Russian for user, English for code
- Commit messages in English, imperative mood
- All prompts in `prompts/` directory, versioned in CHANGELOG.md

## Architecture
```
OCR2 → L1-L4 Pipeline → SMD Core (FSM) → Federal Coordinator
  │         │               │                    │
  │         │        Exploration→Doubt      multi-circuit
  │         │        →Dialogue→Verify       RRF search
  │         │
  │    semiotic/       orchestrator/        federal_coordinator.py
  │    (8 files)       (14 files)           zone_store.py
  │
ocr2_normalizer.py
```

## Module Map
```
src/orchestrator/   — 14 files (provenance, htr_loop, doubt_gate, dialogue_mediator,
                      cross_page_synthesizer, cross_page_linker, smd_core,
                      federal_coordinator, zone_store, engine, meta_reflector,
                      roles/{dispatcher, graph_builder, context_resolver, ...})
src/semiotic/       — 8 files (classifier, extractors, ontology, reflector, cloud_*, mixed_decomposer)
src/normalizer/     — 3 files (ocr2_normalizer, pdf_normalizer, vl_normalizer)
scripts/            — 12 files (ask_orchestrator, run_ocr2_pipeline, generate_dashboard, ...)
HANDOFF.md          — точка входа для нового агента
QWEN.md             — основной контекст
```