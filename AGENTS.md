# AI Canvas — Agent Context

## Project Identity

**AI Canvas** — sovereign C-level analysis and assistance environment. Zero-shot heterogeneous PDF parsing into federated vector-graph knowledge. On-premise, air-gap capable.

**Target user:** CEO/CTO/CIO — non-technical. Interface: natural language only.

**Mission:** восстановить деятельность, породившую документ — не «извлечь данные», а понять, кто, зачем и в какой оргструктуре его создал. Смысл не извлекается из текста — он находится в системе деятельности вне документа.

**Методология:** СМД Г.П. Щедровицкого (Activity Theory + операционно-ролевые позиции).

## Mandatory Reading

1. `docs/CONSTITUTION.md` — 6 principles, architecture constraints
2. `docs/adr/003-constitution-roles.md` — 7 ОРП, конституция v2.1
3. `docs/adr/smd-map.yaml` — SMD-карта деятельности
4. `docs/adr/roles/00-hypotheses.md` — 7 гипотез о промптах
5. `HANDOFF.md` — точка входа для нового агента

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Dispatcher                           │
│            (qwen3.6:35b — dynamic threshold)            │
└─────────────────────────────────────────────────────────┘
        ▲              ▲              ▲              ▲
        │              │              │              │
┌───────┴────┐  ┌──────┴──────┐  ┌───┴───────┐  ┌──┴──────────┐
│  Metadata  │  │   Visual    │  │   Style   │  │  Semantic   │
│ Extractor  │  │ Extractor   │  │ Validator │  │Disambiguator│
│ (PyMuPDF)  │  │(qwen3-vl:30b)│  │(rule-based)│  │(qwen3.6:35b)│
└────────────┘  └─────────────┘  └───────────┘  └──────┬───────┘
                                                       │
                                              ┌────────┴────────┐
                                              │    Context      │
                                              │    Resolver     │
                                              │ (local glossary)│
                                              └────────┬────────┘
                                                       │
                                              ┌────────┴────────┐
                                              │     Graph       │
                                              │    Builder      │
                                              │ (qwen3.6:35b)   │
                                              └─────────────────┘

Stage 1 (parallel):  Metadata Extractor ‖ Visual Extractor
Stage 2 (parallel):  Semantic Disambiguator ‖ Style Validator
Stage 3 (sequential): Context Resolver → Graph Builder
Stage 4 (sequential): Dispatcher → ITERATE | FALLBACK | TERMINATE
```

## Module Map

```
src/
├── orchestrator/
│   ├── engine.py              # Старый Orchestrator (Agent→Reflector→Agent)
│   ├── meta_reflector.py      # ConvergenceDetector, StrategyAdaptor
│   └── roles/                 # НОВОЕ: 7 операционно-ролевых позиций
│       ├── __init__.py
│       ├── metadata_extractor.py
│       ├── visual_extractor.py
│       ├── semantic_disambiguator.py
│       ├── context_resolver.py
│       ├── style_validator.py
│       ├── graph_builder.py
│       └── dispatcher.py
├── agents/
│   ├── dashscope.py
│   └── ollama_local.py
├── pipeline/normalizer.py
└── utils/config.py
data/
├── docs/
└── glossary/psb_org_structure.json
docs/adr/roles/
run_pipeline.py
run_local.py
run_pdf_test.py
HANDOFF.md
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

## How To

```bash
make install        # Установка зависимостей
make test           # pytest -v
make lint           # ruff + mypy

python3 run_pipeline.py data/docs/ЦОД+ПАК.pdf   # 7 ролей, event-bus
python3 run_local.py data/docs/ЦОД+ПАК.pdf      # Старый оркестратор
python3 run_pdf_test.py data/docs/карта.pdf      # Тест загрузки
```

## API Keys

Never hardcoded. macOS keychain via `src/utils/config.py`. Environment fallback: `DASHSCOPE_API_KEY`, `OLLAMA_CLOUD_API_KEY`.

## Repository Rules (HARD)

1. **Never commit to master directly.** Feature branch → PR.
2. **Only aptyp78 merges.** All PRs require aptyp78 approval.
3. **PR checklist:** tests pass, lint passes, constitution compliance.
4. **One PR = one concern.**
5. **Commit messages in English**, imperative mood.

## Parallel Agent Work

| Module | Safe to parallelize with | Risk |
|--------|--------------------------|------|
| `src/orchestrator/roles/metadata_extractor.py` | `visual_extractor.py`, `style_validator.py` | Low |
| `src/orchestrator/roles/semantic_disambiguator.py` | `graph_builder.py`, `context_resolver.py` | Medium |
| `src/orchestrator/roles/dispatcher.py` | Any | **High — координатор** |
| `src/agents/` | `src/orchestrator/roles/*` | Low |
| `data/glossary/` | Any | Low |
| `docs/adr/` | Any | Low |

**Branch naming:** `feat/<module>-<description>`, e.g. `feat/roles-context-resolver`.

## Dependencies

- **Local LLM:** Ollama — qwen3-vl:30b (vision), qwen3.6:35b (reasoning/SMD), qwen3-coder-next (code)
- **Cloud (dev):** DashScope, Ollama Cloud — only when network available
- **Python:** pymupdf, pdfplumber, Pillow, requests
- **Dev:** pytest, ruff, mypy