#!/usr/bin/env python3
"""Тест FSM оркестрации на данных pipeline."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.orchestrator.smd_core import SMDOrchestrationCore


def main():
    # Загружаем данные pipeline
    run_dir = "output"
    pipeline_data = {}
    
    # Загружаем classification
    class_path = f"{run_dir}/01_semiotic_classification.json"
    if Path(class_path).exists():
        with open(class_path) as f:
            pipeline_data["classification"] = json.load(f)
    
    # Загружаем schemas
    schemas_path = f"{run_dir}/03_schemas.json"
    if Path(schemas_path).exists():
        with open(schemas_path) as f:
            raw = json.load(f)
        pipeline_data["schemas"] = {int(k): v for k, v in raw.items()} if isinstance(raw, dict) else {s["page_id"]: s for s in raw}
    
    # Загружаем ontologies
    ont_path = f"{run_dir}/04_ontologies.json"
    if Path(ont_path).exists():
        with open(ont_path) as f:
            pipeline_data["ontologies"] = json.load(f)
    
    # Загружаем reflections
    refl_path = f"{run_dir}/05_reflections.json"
    if Path(refl_path).exists():
        with open(refl_path) as f:
            pipeline_data["reflections"] = json.load(f)
    
    # Список страниц
    pipeline_data["pages"] = list(pipeline_data.get("schemas", {}).keys())[:3]  # Первые 3 страницы
    
    print(f"Загружено данных:")
    print(f"  Страниц: {len(pipeline_data['pages'])}")
    print(f"  Classification: {len(pipeline_data.get('classification', {}))}")
    print(f"  Schemas: {len(pipeline_data.get('schemas', {}))}")
    print(f"  Ontologies: {len(pipeline_data.get('ontologies', []))}")
    print(f"  Reflections: {len(pipeline_data.get('reflections', []))}")
    
    # Запускаем FSM оркестрацию
    print("\nЗапуск FSM оркестрации...")
    core = SMDOrchestrationCore()
    result = core.orchestrate_document(pipeline_data)
    
    # Сохраняем результат
    output_path = f"{run_dir}/10_fsm_orchestration.json"
    with open(output_path, "w") as f:
        json.dump(core.to_dict(result), f, ensure_ascii=False, indent=2)
    
    print(f"\nРезультат сохранён: {output_path}")
    print(f"Сводка: {result.summary}")


if __name__ == "__main__":
    main()
