# HANDOFF — точка входа для нового агента

**Дата:** 2026-07-18
**Ветка:** `feat/orchestrator`
**Статус:** активная разработка

## Что это за проект

**AI Canvas** — суверенная среда анализа и ассистирования для C-level руководителей. Zero-shot парсинг гетерогенных PDF в федеративное векторно-графовое знание. On-premise, air-gap capable.

## Текущее состояние (2026-07-18)

### 4-уровневый семиотический конвейер
- L0: DeepSeek OCR2 (1-3s/стр, локальный MLX) — заменяет Tesseract + Cloud vision
- L1: SMD-классификатор — 7 знаковых форм (discursive, topology, matrix, hierarchy, spatial, enumeration, dynamics)
- L2: Экстракторы схем — Venn, hierarchy, matrix, enumeration, spatial, dynamics
- L3: Онтологический маппер — entities + relations + model
- L4: Прагматический рефлектор — C-level рекомендации

### Оркестратор стратегического мышления (6 модулей)
- `provenance.py` — SHA-256 цепь: PDF → форма → схема → онтология → рекомендация
- `htr_loop.py` — цикл «Гипотеза → Проверка → Пересмотр»
- `cross_page_synthesizer.py` — кросс-страничный семантический граф
- `cross_page_linker.py` — граф связей между зонами (entity-based)
- `doubt_gate.py` — мета-когнитивный вентиль: блокировка LOW-confidence
- `dialogue_mediator.py` — многопозиционная аргументация (advocate/skeptic/synthesizer)
- `smd_core.py` — FSM-контроллер: Exploration → Synthesis → Doubt → Dialogue → Verification

### Данные
- `zone_store.py` — 141 зона × 4096d эмбеддингов, FAISS+SQLite persistence
- `federal_coordinator.py` — мультиконтурный федеративный поиск (RRF-слияние)
- `store.py` — VectorGraphStore (FAISS + SQLite)

### Интерфейс
- `ask_orchestrator.py` — C-level Q&A диспетчер с page-aware retrieval
- `generate_dashboard.py` — интерактивный HTML дашборд
- `QWEN.md` — инструкции для Qwen Code Agent

## Ключевые файлы для чтения

1. `docs/CONSTITUTION.md` — 6 принципов, архитектурные ограничения
2. `QWEN.md` — полная архитектура, модульная карта, протокол взаимодействия
3. `docs/adr/003-constitution-roles.md` — 7 ОРП, конституция v2.2
4. `docs/adr/004-vector-graph-store.md` — FAISS+SQLite, федеративные контуры
5. `docs/verdicts/001-deepseek-ocr2.md` — вердикт по OCR2 (×28 быстрее Cloud)
6. `prompts/CHANGELOG.md` — история изменений промптов

## Последние архитектурные решения

1. **DeepSeek OCR2 принят** (2026-07-18) — заменяет Tesseract + Cloud vision, ×28 быстрее
2. **Federal Coordinator** (2026-07-16) — мультиконтурный федеративный поиск, RRF-слияние
3. **SMD Orchestrator** (2026-07-15) — 6-step strategic thinking engine
4. **Data-Centric AI** (2026-07-15) — зонно-ориентированное хранение вместо страничного

## Что в работе

- [ ] L1 Classifier Agent для OCR2 (image → {needs_vl: true/false})
- [ ] Полный прогон 81 стр. через OCR2-пайплайн
- [ ] Мультифедерация: 2+ документа в Federal Coordinator
- [ ] Per-page онтология + рефлексия (04_ontologies.json, 05_reflections.json)

## Ветки

- `feat/orchestrator` — **активная**, все новые модули
- `feat/production-pipeline` — предыдущая версия (Cloud-пайплайн)

## Быстрый старт

```bash
# Полный OCR2-пайплайн
python3 scripts/run_ocr2_pipeline.py data/docs/Презентация_ИАфр_РАН_финал.pdf

# C-level Q&A
python3 scripts/ask_orchestrator.py "Какие риски?"

# Дашборд
python3 scripts/generate_dashboard.py output/run_ocr2_*/
open output/run_ocr2_*/08_dashboard.html
```