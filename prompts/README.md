# Prompt Library

Версия: 1.0.0 | Обновлено: 2026-07-13

## Структура

```
prompts/
├── README.md                    # этот файл
├── VERSION                      # версия библиотеки промптов
├── CHANGELOG.md                 # история изменений
├── orchestrator/                # роли ОРП (7 шт.)
│   ├── domain_analyzer.md       # SMD domain detection (v2.0)
│   ├── dispatcher.md            # iteration & SLA dispatcher (v1.0)
│   ├── semantic_disambiguator.md # разрешение терминов (v1.0)
│   ├── graph_builder.md         # построение графа (v1.0)
│   ├── context_resolver.md      # внешний контекст (v2.0)
│   ├── style_validator.md       # валидация форматирования (v1.0)
│   └── metadata_extractor.md    # извлечение метаданных (v1.0)
├── normalizer/                  # L0 нормализатор (2 шт.)
│   ├── zone_separator.md        # разделение зон mixed-страниц (v1.0)
│   └── image_content_extractor.md # извлечение текста из картинок (v1.0)
└── engine/                      # ядро оркестратора (4 шт.)
    ├── agent.md                 # агент структурного анализа (v1.0)
    ├── reflector.md             # рефлектор (v1.0)
    ├── focus.md                 # уточняющий анализ (v1.0)
    └── meta_reflector.md        # адаптивные стратегии (v1.0)
```

## Правила

1. **Промпты — в .md файлах.** Ни один промпт не встраивается в код.
2. **Каждый промпт версионируется.** Версия в заголовке файла.
3. **Изменения — в CHANGELOG.md.** Дата, файл, версия, описание.
4. **Методологический аудит** — через облачную qwen3.7-plus перед коммитом.
5. **Формат:** `[РОЛЬ]...[ОГРАНИЧЕНИЕ]` для ролевых ОРП; `## ЗАДАЧА...## ФОРМАТ` для свободных.

## Модели

| Модель | Промпты |
|--------|---------|
| qwen3-vl:30b (vision) | zone_separator, image_content_extractor, agent, focus |
| qwen3.6:35b (reasoning) | domain_analyzer, dispatcher, semantic_disambiguator, graph_builder, context_resolver, reflector, meta_reflector |