# AI Canvas — Copilot Instructions

You are working on **AI Canvas** — sovereign C-level analysis environment. Zero-shot PDF parsing into federated vector-graph knowledge. On-premise, air-gap capable.

## Context
7 операционно-ролевых позиций (ОРП) по методологии СМД Г.П. Щедровицкого. Каждая роль — замкнутый модуль со своим контрактом. Промпты — роли, не инструкции: `[РОЛЬ]...[ОГРАНИЧЕНИЕ]`. Смысл не извлекается из текста — он восстанавливается из деятельности.

## Rules
- `make lint` before commit (ruff + mypy)
- Python 3.12+, static typing
- Роли не вызывают другие роли — координация через Dispatcher
- SEMANTIC_GAP — правильный ответ, не галлюцинируй расшифровки
- Russian for user, English for code
- Commit messages in English, imperative mood

## Architecture
Dispatcher → parallel: Metadata ‖ Visual, Disambiguator ‖ Validator → sequential: Context Resolver → Graph Builder. EventBusPipeline in `src/orchestrator/roles/dispatcher.py`.

## Module Map
```
src/orchestrator/roles/  — 7 ролей (metadata, visual, disambiguator, context, style, graph, dispatcher)
src/agents/              — ollama_local (основной), dashscope (облако)
data/glossary/           — psb_org_structure.json (15 терминов ПСБ)
run_pipeline.py          — точка входа: 7 ролей + event-bus
HANDOFF.md               — контекст для нового агента
```