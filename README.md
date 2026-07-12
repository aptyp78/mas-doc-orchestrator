# MAS Doc Orchestrator

Универсальный (zero-shot) оркестратор с циклами рефлексии для парсинга гетерогенных PDF-документов в векторно-графовый формат.

## Архитектура

```
Agent (qwen3-vl-plus) → Reflector (qwen3.6-35b-a3b) → Agent → ... → Stabilisation
```

- **L0 Physical Decomposer:** PyMuPDF — классификация примитивов страницы (текст, вектор, растр)
- **L1 Modality Router:** определяет тип контента (Text / Table / Diagram / Image / Structured Data)
- **L2 Embedding:** qwen3-embedding:8b (4096d) — векторное представление секций и спанов
- **Pass 2:** графовое уточнение (опционально)

## Установка

```bash
make install
```

API-ключи — в macOS keychain или переменных окружения:

```bash
security add-generic-password -a 'dashscope-modelstudio' -w '<ключ>' -T ''
security add-generic-password -a 'ollama-cloud' -w '<ключ>' -T ''
```

## Использование

```bash
make run DOC=путь/к/документу.pdf
make normalize DOC=путь/к/тексту.txt
make test
make lint
```

## Структура

```
src/
├── orchestrator/   # Ядро: Agent → Reflector циклы
├── agents/         # Клиенты: DashScope, Ollama
├── pipeline/       # Нормализатор: Markdown + JSON-sidecar
└── utils/          # Конфигурация
config/             # .env.example
data/docs/          # Тестовые документы
docs/adr/           # Архитектурные решения
scripts/            # Точки входа
tests/              # Тесты
```

## Лицензия

MIT