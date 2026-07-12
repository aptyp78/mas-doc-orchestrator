# ADR-003: SMD Constitution - Roles \& Positions

**Дата:** 2026-07-12 (v2.1 — эмпирически обновлена)
**Статус:** принято (в процессе внедрения)
**Методология:** Системно-методологический подход Георгия Петровича Щедровицкого (Activity Theory)

## Обзор

Конституция деятельности формализуется через фиксацию:
- **Субъекта** (кто действует)
- **Объекта** (чего достигаем)
- **Инструментов** (чем пользуемся)
- **Правил** (как действуем)
- **Сообщества** (с кем работаем)
- **Разделения труда** (кто что делает)

**Противоречия** между элементами — не ошибки, а движущие механизмы эволюции системы.

**Фундаментальный принцип (v2.1):** Смысл не извлекается из текста — он восстанавливается из деятельности, породившей документ. Документ — не самодостаточный источник смысла, а след системы деятельности, оставившей в нём указатели на внешние структуры (оргструктуру, глоссарий, доменную онтологию). Система не парсит документ — она восстанавливает деятельность, которая его породила.

## Актуальная конституция

| Элемент | Описание |
|---------|----------|
| **Субъект** | Dispatcher + 7 Specialists (оркестратор ОРП) |
| **Объект** | PDF → восстановленная деятельность (структурированные данные + метаданные + семантические связи + внешние референсы + provenance) |
| **Цель** | Достижение целевой accuracy в рамках SLA ≤ 5 мин, с явным различением: извлечённое из документа vs восстановленное из внешней деятельности |
| **Инструменты** | LLM (qwen3-vl/3.6) + Vector/Graph cache + Metadata parser + Style validator + Async scheduler + Light-weight State Machine + **Local glossary + Domain ontology** |
| **Правила** | Динамический порог по классу документа; итерации ≤2 deep + 1 heuristic; fallback-маршруты (rule-based → human); **SEMANTIC_GAP → External Context Resolver → EXTERNAL_GAP → human-in-the-loop** |
| **Разделение труда** | Параллельно-последовательная оркестрация 7 ОРП: Extract → Disambiguate → (Resolve external) → Validate → Dispatch (feedback по графу зависимостей) |

## Операционно-rolевые позиции (ОРП)

### ОРП 1: Metadata \& Provenance Extractor

| Параметр | Значение |
|----------|----------|
| **Объект** | Исходные атрибуты PDF (Author, CreateDate, Revision, PageCount) |
| **Инструменты** | `pypdf`, `pdfminer.six`, EXIF/IDat парсер |
| **Правила** | Фиксация ≥8 атрибутов; fallback на пустые значения с пометкой `MISSING` |
| **Рефлектор (L1)** | Проверка полноты |
| **Рефлектор (L2)** | Логирование пропусков |

### ОРП 2: Semantic Disambiguator

| Параметр | Значение |
|----------|----------|
| **Объект** | Аббревиатуры, термины, кросс-ссылки |
| **Инструменты** | Vector cache / lightweight graph DB; LLM with few-shot linking |
| **Правила** | Кэширование развёртки ≤50 токенов; связывание ≥90% по контексту |
| **Рефлектор (L1)** | Coverage cross-ref |
| **Рефлектор (L2)** | Граф связности (≥3 hop) |

### ОРП 3: Style \& Format Validator

| Параметр | Значение |
|----------|----------|
| **Объект** | HEX/RGB, векторные примитивы, layout-паттерны |
| **Инструменты** | Цветовые профили, SVG-анализатор, rule-based checklist |
| **Правила** | Соответствие спецификации ≤5% отклонений; генерация diff-карты стилей |
| **Рефлектор (L1)** | Compliance score |
| **Рефлектор (L2)** | Warning/failure threshold split |

### ОРП 4: Iteration \& SLA Dispatcher

| Параметр | Значение |
|----------|----------|
| **Объект** | Циклы оценки, таймауты, fallback-стратегии |
| **Инструменты** | Async task scheduler, timeout guard, confidence dynamics calculator |
| **Правила** | Динамический порог по классу документа; max 2 deep iterations + 1 heuristic fallback |
| **Рефлектор (L1)** | Latency tracker |
| **Рефлектор (L2)** | Resource exhaustion handler |

### ОРП 5: Visual Extractor

| Параметр | Значение |
|----------|----------|
| **Объект** | Растровое изображение страницы → примитивы (text blocks, vector paths, raster regions) |
| **Инструменты** | PyMuPDF (fitz) — page rasterization + text layer extraction |
| **Правила** | Классификация страницы: text-only \| image-only \| mixed (текст+вектор) \| mixed (текст+изображения); drawings → classify (decorative \| structural \| table) |
| **Рефлектор (L1)** | Completeness check |
| **Рефлектор (L2)** | Spatial relation consistency |

### ОРП 6: Graph Builder

| Параметр | Значение |
|----------|----------|
| **Объект** | Установление связей между блоками (contains, adjacent_to, aligned_with) |
| **Инструменты** | LLM reasoning + spatial analysis |
| **Правила** | Не более 3 hops в графе; confidence ≥0.8 для связи; логирование orphan-узлов |
| **Рефлектор (L1)** | Graph completeness (coverage %) |
| **Рефлектор (L2)** | Contradiction detection (conflicting relations) |

### ОРП 7: External Context Resolver

| Параметр | Значение |
|----------|----------|
| **Объект** | Единицы с SEMANTIC_GAP → разрешение через внешние источники в закрытом контуре |
| **Инструменты** | Локальный глоссарий, доменная онтология, оргструктура банка, human-in-the-loop |
| **Правила** | Поиск: глоссарий → онтология → человек; не найдено → EXTERNAL_GAP (требуется пополнение глоссария); запрет облачных API |
| **Рефлектор (L1)** | Проверка: все SEMANTIC_GAP обработаны? Источник указан для каждого? |
| **Рефлектор (L2)** | Динамика EXTERNAL_GAP: если глоссарий не пополняется → сигнал Dispatcher |

**Методологическое основание:** Смысл не содержится в тексте. Смысл возникает в деятельности, породившей документ. Аббревиатура «БИБ» — не текст, а след организационного решения. Context Resolver обращается не к документу, а к системе деятельности, стоящей за документом.

## Противоречия

### Primary Contradiction
```
elements: tools:agent_model, rules:max_latency_seconds
issue: High confidence requires deep analysis which exceeds 5min SLA on M5 Max
resolution: Разделение труда → Dispatcher + Specialists (параллельная обработка)
```

### Secondary Contradiction
```
elements: subject:c_level_expectations, tools:local_llm_quality  
issue: C-level expects expert-level accuracy but local models may lack domain-specific knowledge
resolution: Введение Semantic Disambiguator для контекстной памяти и разрешения неоднозначностей
```

### Ternary Contradiction
```
elements: community:air_gap_required, rules:cloud_model_updates
issue: Air-gap prevents cloud-based model updates for new document types
resolution: Context Keeper (lightweight cache) как отдельный слой для накопления знаний
```

## Expansionary Paths

| Путь | Описание |
|------|----------|
| **Распаковать рефлектор на ОРП** | Вынести логику метаданных, дисамбигуации и стиля в отдельные модули-ОРП с чёткими интерфейсами |
| **Ввести динамический порог** | Вместо жёсткого `0.85` использовать `threshold(class)` + поправку на сложность (размер документа, плотность текста) |
| **Заменить линейный цикл на граф зависимостей** | ОРП работают параллельно где возможно; рефлексия L1/L2 идёт в оркестратор без блокировки глубоких вызовов |
| **Добавить Stabilizer ORM** | Перед каждым переходом в SM проверять структурную целостность (JSON-schema validation, required fields) |

## Рефлексия уровней

### L0: Physical Decomposer
- Инструмент: PyMuPDF
- Роль: Разбор страницы на примитивы (text_run, vector_path, raster_sample)
- Выход: Primitive map with spatial locations

### L1: Operational Roles Execution
- Инструмент: Локальные модули ОРП
- Роль: Выполнение конкретных операций (Extract → Disambiguate → Validate → Dispatch)
- Выход: Частичный результат с метаданными и validation status

### L2: Meta-reflection on Roles
- Инструмент: MetaReflector классы
- Роль: Анализ противоречий между ролевыми позициями, адаптация стратегии
- Выход: Рекомендации по эволюции конституции

### L3: Constitution Evolution
- Инструмент: Human + SMD methodology
- Роль: Формализация новых ОРП и правил на основе выявленных противоречий
- Выход: Обновлённая конституция проекта

## Внедрение (Phase 1)

### Шаг 1: Распаковать рефлектор на ОРП
Создать отдельные модули:
```
src/orchestrator/roles/
├── __init__.py
├── metadata_extractor.py      # Metadata & Provenance Extractor
├── semantic_disambiguator.py  # Semantic Disambiguator  
├── style_validator.py         # Style \& Format Validator
└── dispatcher.py              # Iteration \& SLA Dispatcher
```

### Шаг 2: Ввести динамический порог
```python
# config.py
def dynamic_threshold(doc_class: str) -> float:
    """Динамический порог по классу документа."""
    thresholds = {
        "text_only": 0.75,
        "mixed_text_vector": 0.80,
        "mixed_text_image": 0.82,
        "complex_diagram": 0.88
    }
    return thresholds.get(doc_class, 0.85)
```

### Шаг 3: Реализовать fallback-маршруты
```python
# When max iterations exceeded or SLA reached:
- rule-based extraction (heuristic rules for common patterns)
- partial output with `NEEDS_REVIEW` flag
- audit log entry for human review
```

## Ссылки

- [ADR-001: Orchestrator with reflection cycles](./001-orchestrator-reflection.md)
- [ADR-002: Системно-методологический подход (СМД)](./002-smg.md)
- [SMD Map (YAML)](./smd-map.yaml)
- [Методология Щедровицкого — Московский методологический круг](https://ru.wikipedia.org/wiki/Щедровицкий,_Геннадий_Алексеевич)
