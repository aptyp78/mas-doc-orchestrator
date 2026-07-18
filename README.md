# AI Canvas — MAS Doc Orchestrator

Суверенный (zero-shot) оркестратор стратегического мышления для C-level руководителей. Парсинг гетерогенных PDF в федеративное векторно-графовое знание. On-premise, air-gap capable.

## Архитектура

```
PDF → DeepSeek OCR2 (1-3s/стр, MLX) → L1-L4 Pipeline → C-level Recommendations
                                          │
                                          ├── SMD Core (FSM): Exploration→Doubt→Dialogue→Verification
                                          ├── Federal Coordinator (RRF): multi-circuit search
                                          └── Qwen Code Agent: ask_orchestrator.py
```

- **L0:** DeepSeek OCR2 — локальный OCR (MLX, Apple Silicon), ×28 быстрее Cloud
- **L1:** Семиотический классификатор — 7 SMD-форм (discursive, topology, matrix, hierarchy, spatial, enumeration, dynamics)
- **L2:** Экстракторы схем — Venn, hierarchy, matrix, enumeration, spatial, dynamics
- **L3:** Онтологический маппер — entities + relations + model
- **L4:** Прагматический рефлектор — C-level рекомендации

## Оркестратор стратегического мышления

6 модулей: provenance (SHA-256), htr_loop (гипотезы), doubt_gate (блокировка), dialogue_mediator (advocate/skeptic/synthesizer), cross_page_synthesizer (граф), smd_core (FSM).

## Установка

```bash
make install
```

API-ключи — в macOS keychain или переменных окружения:

```bash
security add-generic-password -a 'dashscope-modelstudio' -w '<ключ>' -T ''
```

## Быстрый старт

```bash
# OCR2-пайплайн (локальный, ~3 мин на 81 стр.)
python3 scripts/run_ocr2_pipeline.py data/docs/Презентация_ИАфр_РАН_финал.pdf

# C-level Q&A
python3 scripts/ask_orchestrator.py "Какие риски для России в Африке?"

# Дашборд
python3 scripts/generate_dashboard.py output/run_ocr2_*/
open output/run_ocr2_*/08_dashboard.html

# Федеративный поиск по 2+ документам
python3 -c "
from src.orchestrator.federal_coordinator import FederalCoordinator
fc = FederalCoordinator()
fc.register_circuit('doc1', 'output/run_1/')
fc.register_circuit('doc2', 'output/run_2/')
print(fc.search('минеральные ресурсы'))
"
```

## Структура

```
src/
├── semiotic/          8 файлов  — L1-L4 конвейер
├── orchestrator/     14 файлов  — ядро оркестрации + федерация
├── normalizer/        3 файла   — OCR2, PDF, VL
├── agents/            3 файла   — DashScope, Ollama, Brave
├── store.py                     — VectorGraphStore (FAISS+SQLite)
└── utils/config.py              — LazyKey (keychain → env)

scripts/              12 файлов  — запуск, дашборд, Q&A, валидация
prompts/              14 .md     — все промпты (CHANGELOG + AUDIT)
docs/                  ADR, конституция, вердикты
output/run_*/          результаты прогонов
```

## Конституция

6 принципов: Суверенность, Zero-Shot, Языковая нативность, Федеративность, Provenance, Непрерывное обучение. Подробнее: `docs/CONSTITUTION.md`.

## Лицензия

MIT