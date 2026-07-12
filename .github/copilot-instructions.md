# AI Canvas — Copilot Instructions

You are working on **AI Canvas** — a sovereign C-level analysis and assistance environment for zero-shot heterogeneous PDF parsing into federated vector-graph knowledge.

## Context

The project is on-premise, air-gap capable. Target user: CEO/CTO/CIO — non-technical. Interface: natural language only (Open WebUI / AnythingLLM).

## Rules

- Read `docs/CONSTITUTION.md` before any architectural change
- All communication with user in Russian; code identifiers, comments, commit messages in English
- Python 3.12+, static typing, `ruff` linting (E, F, I, N, W, UP), line length 120
- No premature abstraction. No comments that narrate code — only *why*.
- API keys from keychain or env, NEVER hardcoded.
- `make lint` must pass before commit. `make test` must pass.
- Never commit to master directly. Feature branches → PR → aptyp78 review → merge.
- One PR = one concern. Commit messages in English, imperative mood.

## Architecture

```
L0 (PyMuPDF text/vector/raster) → L1 (Vision LLM: modality routing) → L2 (embedding, 4096d) → Pass 2 (graph refinement)
```

Orchestrator: Agent → Reflector → Agent → ... confidence-gated.

## Module Map

- `src/orchestrator/engine.py` — Core Agent → Reflector → Agent loop
- `src/agents/dashscope.py` — DashScope + Ollama API clients
- `src/pipeline/normalizer.py` — Raw text → Markdown + JSON-sidecar
- `src/utils/config.py` — LazyKey: keychain → env fallback
- `tests/test_config.py` — Key availability tests
- `scripts/run_orchestrator.py` — Entry: PDF → orchestrator
- `scripts/run_normalize.py` — Entry: text → normalized output