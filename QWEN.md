# AI Canvas — Agent Context

## Project Identity

**AI Canvas** — sovereign C-level analysis and assistance environment. Zero-shot heterogeneous PDF parsing into federated vector-graph knowledge. On-premise, air-gap capable.

**Target user:** CEO/CTO/CIO — non-technical. Interface: natural language only.

**Mission:** восстановить деятельность, породившую документ — не «извлечь данные», а понять, кто, зачем и в какой оргструктуре его создал. Смысл не извлекается из текста — он находится в системе деятельности вне документа.

**Методология:** СМД Г.П. Щедровицкого (Activity Theory + операционно-ролевые позиции). Смысл возникает в деятельности, а не содержится в тексте. **Смысловые ходы:** трансформация смысла на каждом уровне конвейера (L0→L1→L2→L3→L4). Детали: `docs/SEMANTIC_FLOW.md`

## Два режима работы

Система работает в двух режимах, обеспечивающих трансформацию детерминированных данных в стохастические:

### Режим 1: Pipeline трансформации (roles/)

**Назначение:** Загрузка новых документов. Трансформация PDF (детерминированное) → ZoneStore (стохастическое: эмбеддинги, графы).

**Компоненты:**
- `src/orchestrator/roles/` — 7 ОРП (операционно-ролевых позиций)
- `EventBusPipeline` в `roles/dispatcher.py` — оркестрация ОРП
- `run_pipeline.py` — точка входа для загрузки документов

**Процесс:** PDF → Metadata Extractor → Visual Extractor → Semantic Disambiguator → Style Validator → Graph Builder → Context Resolver → Dispatcher → ZoneStore

**Результат:** Документ загружен в ZoneStore, готов к запросам.

### Режим 2: Интерфейс к стохастическим данным (ask_orchestrator)

**Назначение:** Быстрый поиск и LLM-инференс по уже загруженным данным.

**Компоненты:**
- `scripts/ask_orchestrator.py` — C-level Q&A интерфейс
- `ZoneStore` — хранилище стохастических данных
- `CrossPageLinker`, `DoubtGate`, `DialogueMediator` — модули анализа

**Процесс:** Вопрос → ZoneStore (поиск) → CrossPageLinker (связи) → DoubtGate (confidence) → LLM (генерация) → Ответ с provenance

**Результат:** Ответ на вопрос с ссылками на источники.

### Соотношение режимов

```
Pipeline трансформации (roles/)
  PDF ──→ ОРП 1..7 ──→ ZoneStore (эмбеддинги, графы)
  Детерминированное ──→ Стохастическое
         │
         ▼
Интерфейс (ask_orchestrator.py)
  Вопрос ──→ ZoneStore ──→ LLM ──→ Ответ с provenance
  Быстрый поиск + LLM-инференс
```

**Ключевой принцип:** Pipeline выполняется один раз при загрузке. Интерфейс работает с трансформированными данными многократно.

## Mandatory Reading

1. `docs/CONSTITUTION.md` — 6 principles, architecture constraints
2. `docs/adr/003-constitution-roles.md` — 7 ОРП, конституция v2.1
3. `docs/adr/smd-map.yaml` — SMD-карта деятельности
4. `docs/adr/roles/00-hypotheses.md` — 7 гипотез о промптах
5. `HANDOFF.md` — точка входа для нового агента

## Architecture

```
                   ┌──────────────────────────────┐
                   │     C-level Manager           │
                   │  «Какие риски? Почему X?»     │
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
│ 4-Level Pipeline │   │  SMD Core (FSM) │   │   Data Layer    │
│  (semiotic/)     │   │  (orchestrator/)│   │  (output/run_*/)│
└─────────────────┘   └─────────────────┘   └─────────────────┘

Pipeline (semiotic/):
  L0: OCR2 (DeepSeek-OCR2-MLX) → Markdown с координатами
  L1: classifier.py        → 7 SMD sign forms
  L2: extractors.py        → schema extraction
  L3: ontology.py          → domain ontology
  L4: reflector.py         → C-level recommendations
  
  **Детали:** `docs/PIPELINE.md` (5-уровневый конвейер)

Orchestrator (orchestrator/):
  provenance.py            → SHA-256 traceability chain
  htr_loop.py              → Hypothesis-Test-Revisit cycle
  cross_page_synthesizer.py → Cross-page semantic graph
  doubt_gate.py            → Confidence gate + unknown zones
  dialogue_mediator.py     → Advocate/Skeptic/Synthesizer
  smd_core.py              → FSM: Exploration→Synthesis→Doubt→Dialogue→Verification

Data Layer:
  output/run_*/01_semiotic_classification.json
  output/run_*/03_schemas.json                    (529 KB)
  output/run_*/07_recommendations.json            (18 recs)
  output/run_*/08_dashboard.html
```

## Orchestration Modes (FSM)

```
Exploration → Synthesis → Doubt → Dialogue → Verification → Complete
     │            │          │         │            │
     │            │          │         │            └─ Provenance trace
     │            │          │         └─ Multi-position argumentation
     │            │          └─ Block LOW-confidence, map unknowns
     │            └─ Cross-page graph, clusters, leverage points
     └─ HTR cycle: generate hypotheses → verify → revise
```

**Transitions:**
- LOW confidence → Doubt → Dialogue (автоматически)
- Contradiction found → Doubt → revisit
- All clear → Verification → Complete
- User asks «почему?» → Provenance trace
- User asks «а что если?» → Exploration (HTR)

## Module Map

```
src/
├── semiotic/
│   ├── classifier.py           # L1: SMD sign form classification
│   ├── cloud_classifier.py     # L1: Cloud (DashScope) classifier
│   ├── extractors.py           # L2: Schema extractors (venn, hierarchy, matrix, etc.)
│   ├── ontology.py             # L3: Domain ontology mapper
│   ├── cloud_ontology.py       # L3: Cloud ontology mapper
│   ├── reflector.py            # L4: C-level pragmatic reflector
│   ├── cloud_reflector.py      # L4: Cloud reflector
│   └── mixed_decomposer.py     # P2: Mixed page decomposition
├── orchestrator/
│   ├── engine.py               # Legacy Orchestrator (Agent→Reflector→Agent)
│   ├── meta_reflector.py       # ConvergenceDetector, StrategyAdaptor
│   ├── provenance.py           # NEW: SHA-256 traceability chain
│   ├── htr_loop.py             # NEW: Hypothesis-Test-Revisit cycle
│   ├── cross_page_synthesizer.py # NEW: Cross-page semantic graph
│   ├── doubt_gate.py           # NEW: Meta-cognitive confidence gate
│   ├── dialogue_mediator.py    # NEW: Advocate/Skeptic/Synthesizer
│   ├── smd_core.py             # NEW: FSM orchestration core
│   └── roles/                  # 7 операционно-ролевых позиций
│       ├── dispatcher.py
│       ├── graph_builder.py
│       ├── context_resolver.py
│       └── ...
├── agents/
│   ├── dashscope.py
│   └── ollama_local.py
├── store.py                    # VectorGraphStore (FAISS + SQLite)
├── confidence_guard.py         # Stagnation/divergence/overfitting detection
└── utils/config.py             # LazyKey: keychain → env fallback

scripts/
├── run_cloud_pipeline.py       # Full 81-page Cloud pipeline
├── generate_dashboard.py       # HTML dashboard generator
├── generate_recommendations.py # Single-request C-level recommendations
├── batch_ontology_local.py     # Local batch ontology+reflector
├── resume_cloud_ontology.py    # Cloud ontology resumer
├── ask_orchestrator.py         # NEW: C-level Q&A dispatcher
└── ...

data/docs/                      # Test PDFs
data/glossary/psb_org_structure.json
output/run_*/                   # Pipeline results
prompts/                        # Versioned LLM prompts (.md)
docs/adr/                       # Architecture Decision Records
```

## C-Level Interaction Protocol

### When Qwen Code answers a C-level question:

1. **LOAD** — read latest `output/run_*/07_recommendations.json` and `03_schemas.json`
2. **ROUTE** — classify question type:
   - «какие риски/возможности?» → read recommendations, apply doubt_gate
   - «почему рекомендация X?» → provenance trace
   - «что на странице N?» → read schema, show entities + conclusion
   - «а что если...?» → HTR loop (hypothesis generation)
   - «как связаны X и Y?» → cross-page graph
3. **DOUBT-CHECK** — before answering, run doubt_gate. If confidence < 0.65, say so.
4. **MULTI-POSITION** — for strategic questions, present advocate/skeptic/synthesizer views
5. **PROVENANCE** — cite source page and sign form for every claim

### Answer format:

```
🔴/🟡/🟢 [URGENCY] Краткий ответ (1 предложение)

📄 Источник: стр. N, форма: topology/discursive/...
🔗 Provenance: [sign_form] → [schema] → [ontology] → [recommendation]

[ADVOCATE] Аргумент ЗА: ...
[SKEPTIC] Аргумент ПРОТИВ: ...
[SYNTHESIZER] Компромисс: ...

⚠️ Зоны неизвестности: ...
```

### Example:

```
C-level: Какие риски для России в Африке?

Qwen Code:
🔴 Риски (стр. 9, 11, 14):

1. Вытеснение конкурентами — США, ЕС, Китай контролируют цепочки поставок
   📄 стр. 9, topology: Venn-диаграмма USA/EU/China
   🔗 topology → 3 sets, 30+ minerals → 12 entities, 7 relations → HIGH urgency

2. Эксклюзивные сделки блокируют доступ к активам
   📄 стр. 9, topology: зона пересечения USA/EU

[ADVOCATE] Риски реальны: Африка — 15% мирового производства, 74% бокситов
[SKEPTIC] Россия может войти через суверенное финансирование, обходя конкурентов
[SYNTHESIZER] Фокус на олово/хром/уран — ниши с меньшей конкуренцией

⚠️ Неизвестно: точные объёмы российских инвестиций в Африке на 2026 г.
```

## Running the Orchestrator

```bash
# Ask a question to the orchestrator
python3 scripts/ask_orchestrator.py "Какие риски для России в Африке?"

# Specify run directory
python3 scripts/ask_orchestrator.py --run output/run_2026-07-15_1107 "Почему рекомендация по олову?"

# Full pipeline (81 pages, Cloud + local)
python3 scripts/run_cloud_pipeline.py data/docs/Презентация_ИАфр_РАН_финал.pdf

# Generate dashboard from existing run
python3 scripts/generate_dashboard.py output/run_2026-07-15_1107/
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
- **Всегда с provenance.** Никаких утверждений без ссылки на страницу и знаковую форму.
- **Всегда с doubt_gate.** Если confidence < 0.65 — честно предупреди.
- **Всегда multi-position.** Для стратегических вопросов — advocate/skeptic/synthesizer.
- **Не выдумывай.** Если данных нет — скажи «недостаточно данных».

## Repository Rules (HARD)

1. **Never commit to master directly.** Feature branch → PR.
2. **Only aptyp78 merges.** All PRs require aptyp78 approval.
3. **PR checklist:** tests pass, lint passes, constitution compliance.
4. **One PR = one concern.**
5. **Commit messages in English**, imperative mood.

## Dependencies

- **Local LLM:** Ollama — qwen3-vl:30b (vision), qwen3.6:35b (reasoning/SMD), qwen3-coder-next (code)
- **Cloud (dev):** DashScope, Ollama Cloud — only when network available
- **Python:** pymupdf, pdfplumber, Pillow, requests, networkx (optional)
- **Dev:** pytest, ruff, mypy

## Memory

Project memory: `~/.qwen/projects/-Users-arturoceretnyj/memory/`.
Update when: new architectural decision, model config change, significant test result.