[РОЛЬ] Синтезатор макро-структуры документа
[ПРЕДМЕТ] Сводка онтологий {n_pages} страниц + граф связей
[ЗАДАЧА] Выяви макро-структуру документа:
1. Кластеры страниц (тематические блоки)
2. Скрытые драйверы изменений (latent drivers)
3. Ключевые точки leverage (где минимальное воздействие даёт максимальный эффект)
4. Стратегические противоречия (conflicting signals)
[ОГРАНИЧЕНИЕ] Только на основе данных. Не выдумывай.

Формат: JSON
{{
  "clusters": [{{"name": "string", "pages": [N], "theme": "string"}}],
  "latent_drivers": ["string"],
  "leverage_points": [{{"page": N, "description": "string", "impact": "HIGH|MEDIUM|LOW"}}],
  "strategic_contradictions": [{{"pages": [N, M], "description": "string"}}]
}}

## СВОДКА ОНТОЛОГИЙ
{summary}

## ГРАФ СВЯЗЕЙ
{edges}