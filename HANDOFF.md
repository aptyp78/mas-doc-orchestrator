# HANDOFF: от облачной DeepSeek V4 Pro → локальному qwen3-coder-next

**Дата:** 2026-07-12 16:45 YEKAT
**От:** DeepSeek V4 Pro (облако) + пользователь
**Кому:** qwen3-coder-next (локальный Ollama, M5 Max, 128GB, 262K ctx)
**Режим:** air-gap (в полёте, сеть нестабильна)
**Репозиторий:** https://github.com/aptyp78/mas-doc-orchestrator

---

## 1. ГДЕ МЫ СЕЙЧАС

### Проект: AI Canvas / MAS Doc Orchestrator
Технология универсального zero-shot парсинга PDF через Multi-Agent System с циклами рефлексии. Методологическая основа — СМД Г.П. Щедровицкого (Activity Theory + операционно-ролевые позиции).

### Последний коммит: `9541a97`
```
feat: event-bus pipeline + glossary fix + карта.pdf test
```

### Что работает (проверено сегодня)

```
src/orchestrator/roles/     ← 7 ролей, каждая — замкнутый модуль
├── metadata_extractor.py   ← PyMuPDF, без LLM
├── visual_extractor.py     ← qwen3-vl:30b (vision)
├── semantic_disambiguator.py ← qwen3.6:35b (text)
├── context_resolver.py     ← локальный глоссарий
├── style_validator.py      ← rule-based
├── graph_builder.py        ← qwen3.6:35b (reasoning)
└── dispatcher.py           ← Pipeline + EventBusPipeline + Dispatcher

data/glossary/psb_org_structure.json  ← 15 терминов ПСБ

docs/adr/roles/             ← 7 спецификаций ролей + валидация + гипотезы
docs/adr/003-constitution-roles.md  ← конституция v2.1
docs/adr/smd-map.yaml       ← SMD-карта v2.1
```

### Результаты прогонов

| Документ | Пайплайн | Confidence | Время | Dispatcher |
|----------|---------|------------|-------|------------|
| ЦОД+ПАК.pdf | EventBus | 1.0 | 191s | TERMINATE |
| карта.pdf | EventBus | 0.94 | 160s | ITERATE |

### Ключевое достижение
БИБ = «Блок информационной безопасности» — Context Resolver + глоссарий дали правильный ответ. Старый AGENT_PROMPT галлюцинировал 3 разных варианта.

---

## 2. ЧТО ДЕЛАТЬ ДАЛЬШЕ (приоритет)

### P0: Эксперименты с ролевыми промптами на локальном инференсе
Взять спецификации ролей из `docs/adr/roles/0*.md`, прогнать каждую роль отдельно на реальных данных, сравнить role-prompt vs instruction-prompt. Гипотезы уже сформулированы в `docs/adr/roles/00-hypotheses.md`. H1 и H2 подтверждены, H6 и H7 — новые.

### P1: Обновить конституцию и знания проектные
После экспериментов — обновить `docs/adr/003-constitution-roles.md` и `docs/adr/smd-map.yaml` с учётом новых данных. Зафиксировать в `memory/` проектной памяти.

### P2: Интеграция ролей в engine.py
Сейчас `engine.py` использует старый Orchestrator (Agent→Reflector→Agent). Новый Pipeline лежит в `dispatcher.py`. Нужно заменить или предоставить выбор.

### P3: Второй раунд рефлексии по SMD
После экспериментов — прогнать результаты через qwen3.6:35b с методологическим промптом и уточнить understanding.

---

## 3. КАК ЗАПУСКАТЬ

```bash
cd /Users/arturoceretnyj/mas-doc-orchestrator

# Ролевой пайплайн (7 ролей, event-bus)
python3 run_pipeline.py data/docs/ЦОД+ПАК.pdf

# Старый оркестратор (Agent→Reflector→Agent)
python3 run_local.py data/docs/ЦОД+ПАК.pdf

# Тест загрузки PDF (без LLM)
python3 run_pdf_test.py data/docs/карта.pdf

# Линт
ruff check src/ --fix && ruff format src/

# Типы
mypy src/ --ignore-missing-imports
```

---

## 4. АРХИТЕКТУРНЫЕ РЕШЕНИЯ (не ломать)

1. **Роли не вызывают друг друга.** Координация — только через Dispatcher/Pipeline.
2. **qwen3-vl:30b для vision.** Формат: `images` полем (не `content[]` массив). Изображения ≤ 200KB. DPI ≤ 72 для скорости.
3. **qwen3.6:35b для reasoning.** Использовать для Disambiguator, Dispatcher, Graph Builder. Не для vision.
4. **Промпты — роли, не инструкции.** Формат: `[РОЛЬ]...[ОГРАНИЧЕНИЕ]`. Не «опиши блоки», а «ты — Visual Extractor. Ограничение: не интерпретируй семантику».
5. **SEMANTIC_GAP — правильный ответ.** Не пытайся расшифровать то, чего нет в документе. Отправляй в Context Resolver → глоссарий.
6. **Глоссарий — внешний источник смысла.** Пополняется вручную. Air-gap safe.

---

## 5. КОНТЕКСТ, КОТОРЫЙ НУЖНО ПОМНИТЬ

### Методологическая позиция
- Мы не парсим документы. Мы восстанавливаем деятельность, которая их породила.
- Смысл не извлекается из текста — он находится в системе деятельности вне документа.
- Противоречия (SLA vs depth, expectations vs LLM quality, air-gap vs cloud) — движущие механизмы эволюции, не ошибки.
- qwen3.6:35b знает СМД и Activity Theory. qwen3-coder-next — нет. Используй правильную модель для правильной роли.

### Что уже не работает
- DashScope API (сеть недоступна)
- GitHub API (сеть нестабильна) — git push может не работать в полёте

### Что работает локально
- Ollama: qwen3-vl:30b (19GB), qwen3.6:35b (23GB), qwen3-coder-next (51GB)
- PyMuPDF (fitz) — осторожно с `page.rect.width` в f-строках, баг в 1.28.0
- Все роли в `src/orchestrator/roles/`

---

## 6. БЫСТРЫЙ СТАРТ ДЛЯ CODER

```
1. Прочитай docs/adr/003-constitution-roles.md — поймёшь архитектуру
2. Прочитай docs/adr/roles/00-hypotheses.md — поймёшь что проверять
3. Запусти python3 run_pipeline.py data/docs/ЦОД+ПАК.pdf — увидишь пайплайн
4. Смотри вывод в output/pipeline_result.json
5. Экспериментируй с промптами в src/orchestrator/roles/*.py
6. Не ломай формат [РОЛЬ]...[ОГРАНИЧЕНИЕ]
7. Коммить с сообщениями на русском
```

Удачи. Пользователь в полёте, сеть нестабильна. Вся работа — локально на M5 Max.