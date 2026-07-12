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
│       ├── __init__.py        # Role protocol
│       ├── metadata_extractor.py  # PyMuPDF, без LLM
│       ├── visual_extractor.py    # qwen3-vl:30b
│       ├── semantic_disambiguator.py # qwen3.6:35b
│       ├── context_resolver.py     # Локальный глоссарий
│       ├── style_validator.py      # Rule-based
│       ├── graph_builder.py        # qwen3.6:35b
│       └── dispatcher.py           # Pipeline + EventBusPipeline
├── agents/
│   ├── dashscope.py           # DashScope API (не работает без сети)
│   └── ollama_local.py        # Локальный Ollama (основной)
├── pipeline/normalizer.py     # Raw text → Markdown + JSON-sidecar
└── utils/config.py            # LazyKey: keychain → env fallback
data/
├── docs/                      # Test PDFs (ЦОД+ПАК.pdf, карта.pdf)
└── glossary/psb_org_structure.json  # 15 терминов ПСБ
docs/adr/roles/                # Спецификации 7 ролей + валидация + гипотезы
run_pipeline.py                # Вход: PDF → EventBusPipeline (7 ролей)
run_local.py                   # Вход: PDF → старый Orchestrator
run_pdf_test.py                # Вход: PDF → загрузка без LLM
HANDOFF.md                     # Контекст для нового агента
```

## Conventions

### Communication
- **Russian** for all communication with the user and within the project
- **English** for code: identifiers, docstrings, commit messages

### Code
- Python 3.12+, static typing (mypy compatible)
- `ruff` for linting, line length 120
- **Роли не вызывают другие роли.** Координация — только через Dispatcher.
- **Промпты — роли, не инструкции.** Формат: `[РОЛЬ]...[ОГРАНИЧЕНИЕ]`. Не «опиши блоки», а «ты — Visual Extractor. Ограничение: не интерпретируй семантику».
- **SEMANTIC_GAP — правильный ответ.** Не расшифровывай то, чего нет в документе. Отправляй в Context Resolver.
- `make lint` перед коммитом.

### Project structure
- Каждая роль — замкнутый модуль со своим контрактом (вход/выход)
- Глоссарий — внешний источник смысла, пополняется вручную, air-gap safe
- ADR перед каждым архитектурным решением

## How To

```bash
make install        # Установка зависимостей
make test           # pytest -v
make lint           # ruff + mypy

# Ролевой пайплайн (7 ролей, event-bus)
python3 run_pipeline.py data/docs/ЦОД+ПАК.pdf

# Старый оркестратор (Agent→Reflector→Agent)
python3 run_local.py data/docs/ЦОД+ПАК.pdf

# Тест загрузки PDF (без LLM)
python3 run_pdf_test.py data/docs/карта.pdf
```

## API Keys

Keys are NEVER hardcoded. Use macOS keychain:

```bash
security add-generic-password -a 'dashscope-modelstudio' -s 'dashscope-modelstudio-api' -w '<key>' -A
security add-generic-password -a 'ollama-cloud' -s 'ollama-cloud-api' -w '<key>' -A
```

Keys loaded lazily via `src/utils/config.py`. Environment fallback: `DASHSCOPE_API_KEY`, `OLLAMA_CLOUD_API_KEY`.

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
| `data/glossary/` | Any | Low — data-only |
| `docs/adr/` | Any | Low — docs-only |

**Parallel workflow:**
1. Agent A: `feat/roles-visual-extractor`, Agent B: `feat/roles-disambiguator`
2. Both work independently, push to branches
3. PRs → aptyp78 reviews → merges
4. Dispatcher changes require coordination

**Branch naming:** `feat/<module>-<description>`, e.g. `feat/roles-context-resolver`.

## Dependencies

- **Local LLM:** Ollama — qwen3-vl:30b (vision), qwen3.6:35b (reasoning/SMD), qwen3-coder-next (code)
- **Cloud (dev):** DashScope, Ollama Cloud — only when network available
- **Python:** pymupdf, pdfplumber, Pillow, requests
- **Dev:** pytest, ruff, mypy

## Memory

Project memory: `~/.qwen/projects/-Users-arturoceretnyj/memory/`.
Update when: new architectural decision, model config change, significant test result.