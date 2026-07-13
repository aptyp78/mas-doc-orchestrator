# Архитектура MAS Doc Orchestrator

```mermaid
graph TB
    subgraph INPUT["📥 ВХОД: PDF любой природы"]
        PDF["📄 PDF<br/>(текст / картинка / слайд / скан)"]
    end

    subgraph STAGE1["🔵 СТАДИЯ 1: Идентификация + Нормализация (L0)"]
        NORM["pdf_normalizer.py<br/>┌─ PyMuPDF: все примитивы<br/>├─ Классификация страницы<br/>│  ├─ text-only → текст из PDF-слоя<br/>│  ├─ image-only → qwen3-vl:30b + Tesseract<br/>│  └─ mixed → (zone separation опционально)<br/>└─ Выход: Universal Representation"]
    end

    subgraph STAGE2["🟢 СТАДИЯ 2: Доменная принадлежность (SMD)"]
        DOM["domain_analyzer.py<br/>┌─ qwen3.6:35b<br/>├─ 6 шагов Activity Theory<br/>├─ Эмерджентные домены (без predefined list)<br/>├─ Технология = самостоятельный домен<br/>└─ Fuzzy-match → глоссарии"]
    end

    subgraph STAGE3["🟡 СТАДИЯ 3: Анализ + Преобразование"]
        subgraph PARALLEL["Параллельно"]
            META["Metadata Extractor<br/>(PyMuPDF)"]
            DISAMB["Semantic Disambiguator<br/>(qwen3.6:35b)<br/>┌─ Разрешение терминов<br/>└─ SEMANTIC_GAP"]
        end
        
        STYLE["Style Validator<br/>(rule-based)"]
        
        CTX["Context Resolver<br/>┌─ Глоссарий → точное совпадение<br/>├─ LLM-кандидат (qwen3.6:35b)<br/>└─ EXTERNAL_GAP → не блокирует"]
        
        GRAPH["Graph Builder<br/>(qwen3.6:35b)<br/>┌─ nodes + edges<br/>├─ groups + orphans<br/>└─ overall_confidence"]
        
        DISP["Dispatcher<br/>(qwen3.6:35b)<br/>┌─ dynamic threshold<br/>└─ ITERATE | FALLBACK | TERMINATE"]
    end

    subgraph OUTPUT["📤 ВЫХОД"]
        RESULT["pipeline_result.json<br/>┌─ universal: нормализованные примитивы<br/>├─ domain: эмерджентные домены<br/>├─ disambiguator: разрешения + gaps<br/>├─ context_resolver: resolved + candidates<br/>├─ graph: knowledge graph (nodes + edges)<br/>└─ dispatch: решение"]
    end

    subgraph PROMPTS["📋 Промпты (prompts/)"]
        P_ENGINE["engine/<br/>agent, reflector, focus, meta_reflector"]
        P_ORCH["orchestrator/<br/>domain_analyzer, dispatcher,<br/>semantic_disambiguator, graph_builder,<br/>context_resolver, style_validator,<br/>metadata_extractor"]
        P_NORM["normalizer/<br/>zone_separator, image_content_extractor"]
    end

    PDF --> NORM
    NORM -->|"Universal Representation"| DOM
    DOM -->|"Domain-Tagged"| STAGE3
    META --> DISAMB
    DISAMB --> CTX
    CTX --> GRAPH
    GRAPH --> DISP
    STYLE --> GRAPH
    DISP --> RESULT
    
    PROMPTS -.->|"версионируются"| P_ENGINE
    PROMPTS -.->|"CHANGELOG.md"| P_ORCH
    PROMPTS -.->|"аудит: qwen3.7-plus"| P_NORM
```

## Модели

| Модель | Роль | Где |
|--------|------|-----|
| **PyMuPDF** | Детерминированная экстракция | Normalizer, Metadata |
| **qwen3-vl:30b** | Vision (изображения → текст) | Normalizer (image-only) |
| **qwen3.6:35b** | Reasoning (СМД, графы, решения) | Domain, Disambiguator, Context, Graph, Dispatcher |
| **Tesseract** | OCR fallback | Normalizer (image-only) |
| **qwen3.7-plus** ☁️ | Методологический аудит промптов | prompts/AUDIT.md |

## Ключевые принципы

1. **Никаких SKIP** — любой PDF → Universal Representation
2. **Домен эмерджентен** — из структуры деятельности, не из predefined list
3. **Глоссарий не блокирует** — EXTERNAL_GAP = кандидат на пополнение
4. **Промпты версионируются** — prompts/ + CHANGELOG.md + audit