#!/usr/bin/env python3
"""SMD reflection: прогон результатов через локальный qwen3.6 для анализа и уточнения конституции."""
import json
import urllib.request

OLLAMA_LOCAL_BASE = "http://localhost:11434"

# Результат последнего оркестратора (из output)
with open("output/orchestrator_cod_pak_result.json") as f:
    result_data = json.load(f)

reflector_output = result_data["history"][1]["content"]  # Первый рефлектор

analysis_text = f"""
## 🔄 РЕФЛЕКСИЯ НА ДЕЯТЕЛЬНОСТЬ: ОРКЕСТРАТОР С ПРОМПТАМИ

### Литерал: Что делает система?
- **Object**: PDF → структурированные данные
- **Subject**: оркестратор (человек → Agent → Reflector)
- **Tools**: LLM модели (qwen3-vl, qwen3.6), Python state machine

### Анализ промптов через призму СМД:

**ВАЖНО:** Промпты в коде — это не «инструкции для AI», а операционно-ролевые позиции.

### Рефлектор (L1) на output:
{reflector_output[:500]}

### Обнаруженное противоречие:

Contradiction: tools:agent_model vs rules:max_latency_seconds
Issue: High confidence requires deep analysis which exceeds 5min SLA on M5 Max

Результат эксперимента: confidence=0.81 < threshold=0.85 → система продолжает до max_iterations=3.

Это не фиаско, а проявление противоречия — глубина анализа растёт быстрее, чем confidence.
"""

# Промпт для локального LLM
prompt = f"""
Проанализируй следующий SMD-анализ и предложи уточнения для конституции проекта.

Опираясь на методологию Щедровицкого (СМД), выяви:
1. Какие роли не закреплены в деятельности?
2. Какие противоречия требуют нового разделения труда?
3. Какие операционно-ролевые позиции нужно добавить?

{analysis_text}

Ответь структурировано, с конкретными предложениями для конституции.
"""

data = json.dumps({
    "model": "qwen3.6:35b",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 4096,
    "temperature": 0.2,
    "stream": False
}).encode()

req = urllib.request.Request(
    f"{OLLAMA_LOCAL_BASE}/api/chat",
    data=data,
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=300) as resp:
    raw = resp.read().decode("utf-8")
    if "}\n{" in raw:
        for part in raw.split("\n"):
            if part.strip() and part.startswith("{"):
                d = json.loads(part)
                print(d["message"]["content"])
                break
    else:
        d = json.loads(raw)
        print(d["message"]["content"])
