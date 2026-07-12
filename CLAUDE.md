# AI Canvas — Agent Context

## Project Identity

**AI Canvas** — sovereign C-level analysis and assistance environment. Zero-shot heterogeneous PDF parsing into federated vector-graph knowledge. On-premise, air-gap capable.

**Target user:** CEO/CTO/CIO — non-technical. Interface: natural language only (Open WebUI / AnythingLLM).

**Mission:** load document → extract structure → answer questions with provenance and confidence.

## Mandatory Reading

Before any code change, read:
1. `docs/CONSTITUTION.md` — 6 principles, 3 methodological layers, architecture constraints
2. `docs/adr/001-orchestrator-reflection.md` — why reflection cycles, not ensemble

## Architecture

```
L0 Physical Decomposer (PyMuPDF)
  → L1 Modality Router (Vision LLM: Text/Table/Diagram/Image/StructuredData)
    → L2 Embedding (qwen3-embedding:8b, 4096d)
      → Pass 2 Graph Refinement (optional)
```

**Orchestrator:** Agent (qwen3-vl-plus) → Reflector (qwen3.6-35b-a3b) → Agent → ... until confidence ≥ 0.85 or max 3 iterations.

## Module Map

```
src/
├── orchestrator/engine.py   # Core: Agent → Reflector → Agent loop
├── agents/dashscope.py       # DashScope + Ollama API clients
├── pipeline/normalizer.py    # Raw text → Markdown + JSON-sidecar
└── utils/config.py           # LazyKey: keychain → env fallback
tests/
└── test_config.py            # 2 tests (1 skip on keychain)
scripts/
├── run_orchestrator.py       # Entry: PDF → orchestrator
└── run_normalize.py          # Entry: text → normalized output
data/docs/                    # Test documents (ЦОД+ПАК.pdf, карта.pdf)
docs/
├── CONSTITUTION.md           # Project constitution
└── adr/                      # Architecture Decision Records
```

## Conventions

### Communication
- **Russian** for all communication with the user and within the project
- **English** for code: identifiers, comments, commit messages, docstrings
- Technical terms in English where standard (embeddings, confidence, orchestrator)

### Code
- Python 3.12+, static typing (mypy compatible)
- `ruff` for linting (E, F, I, N, W, UP rules), line length 120
- Immutable args preferred; avoid mutation of input parameters
- No premature abstraction — 3 similar lines > 1 premature helper
- No comments that narrate what the code does; only *why* for non-obvious decisions
- `make lint` MUST pass before commit

### Project structure
- Modules by domain responsibility, not by technical type
- Configuration separate from code (`config/`, keychain for secrets)
- ADR before every architectural decision

## How To

```bash
make install        # Install dependencies
make test           # Run tests (pytest -v)
make lint           # Ruff + mypy
make run DOC=<pdf>  # Run orchestrator on a PDF
make normalize DOC=<txt>  # Normalize text output
```

## API Keys

Keys are NEVER hardcoded. Use macOS keychain:

```bash
security add-generic-password -a 'dashscope-modelstudio' -s 'dashscope-modelstudio-api' -w '<key>' -A
security add-generic-password -a 'ollama-cloud' -s 'ollama-cloud-api' -w '<key>' -A
```

Or environment variables: `DASHSCOPE_API_KEY`, `OLLAMA_CLOUD_API_KEY`.

Keys are loaded lazily via `src/utils/config.py` — they don't fail at import.

## Repository Rules (HARD)

1. **Never commit to master directly.** Always feature branch → PR.
2. **Only aptyp78 merges.** Including agents acting on behalf of aptyp78. All PRs require aptyp78 approval.
3. **PR checklist:** tests pass, lint passes, constitution compliance verified.
4. **One PR = one concern.** Don't mix refactoring with features.
5. **Commit messages in English**, imperative mood: "Add X", "Fix Y", "Refactor Z".

## Parallel Agent Work (MAS Development)

This repo is designed for multiple coding agents to work in parallel. Module independence:

| Module | Safe to parallelize with | Conflict risk |
|--------|--------------------------|---------------|
| `src/orchestrator/` | `src/pipeline/`, `src/agents/` | Low |
| `src/pipeline/` | `src/orchestrator/`, `src/agents/` | Low |
| `src/agents/` | `src/orchestrator/`, `src/pipeline/` | Low |
| `src/utils/` | Any | Medium — shared dependency |
| `tests/` | Any | Medium — imports from src |
| `scripts/` | Any | Low — standalone |

**Parallel workflow:**
1. Agent A takes `feat/orchestrator-<task>`, Agent B takes `feat/pipeline-<task>`
2. Both work independently, push to their branches
3. Both open PRs → aptyp78 reviews → merges sequentially
4. If conflicts, last agent resolves merge conflicts

**Branch naming:** `feat/<module>-<short-description>`

## Dependencies

- **Local:** Ollama (qwen3-vl:30b, qwen3.6:35b, qwen3-embedding:8b, qwen3-coder-next)
- **Cloud (dev only):** DashScope (qwen3-vl-plus, qwen3.6-35b-a3b), Ollama Cloud (gemma4:31b, qwen3-coder-next)
- **Python:** pymupdf, pdfplumber, Pillow, requests
- **Dev:** pytest, ruff, mypy