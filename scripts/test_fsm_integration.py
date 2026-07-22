#!/usr/bin/env python3
"""Тест FSM интеграции с моковыми данными."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.orchestrator.smd_core import SMDOrchestrationCore


def main():
    # Загружаем моковые данные
    data_path = "output/test_fsm/pipeline_data.json"
    with open(data_path) as f:
        pipeline_data = json.load(f)
    
    print(f"Загружены моковые данные:")
    print(f"  Страниц: {len(pipeline_data['pages'])}")
    print(f"  Ontologies: {len(pipeline_data['ontologies'])}")
    print(f"  Reflections: {len(pipeline_data['reflections'])}")
    
    # Запускаем FSM
    print("\nЗапуск FSM оркестрации...")
    core = SMDOrchestrationCore()
    result = core.orchestrate_document(pipeline_data)
    
    # Сохраняем результат
    output_path = "output/test_fsm/fsm_result.json"
    with open(output_path, "w") as f:
        json.dump(core.to_dict(result), f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ FSM оркестрация завершена!")
    print(f"Сводка: {json.dumps(result.summary, ensure_ascii=False, indent=2)}")
    
    # Показываем детали по страницам
    for page_id, state in result.page_states.items():
        print(f"\nСтраница {page_id}:")
        print(f"  Режим: {state.mode.name}")
        print(f"  Качество: {state.quality_score:.2f}")
        print(f"  Итерации: {state.iterations}")
        if state.final_recommendation:
            print(f"  Рекомендация: {state.final_recommendation.get('action', '')[:80]}")
        if state.doubt_assessment:
            print(f"  Уверенность: {state.doubt_assessment.confidence:.2f}")
            print(f"  Заблокировано: {state.doubt_assessment.blocked}")
    
    print(f"\nРезультат сохранён: {output_path}")


if __name__ == "__main__":
    main()
