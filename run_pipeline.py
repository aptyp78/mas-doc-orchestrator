#!/usr/bin/env python3
"""Запуск 3-стадийного пайплайна на PDF-файле."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.orchestrator.roles.dispatcher import EventBusPipeline
from src.ingestion.format_detector import prepare_for_pipeline


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 run_pipeline.py <путь к файлу>")
        print("Поддерживаемые форматы: PDF, PPTX, DOCX, PNG, JPG, HTML, MD")
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.isabs(input_path):
        input_path = os.path.join(os.getcwd(), input_path)

    print(f"Входной файл: {input_path}")

    # Format Detector Agent: определяем формат и конвертируем если нужно
    print("\n[Format Detector Agent]")
    processed_path = prepare_for_pipeline(input_path)
    print(f"Готов для pipeline: {processed_path}")

    print(f"\n[Pipeline]")
    pipeline = EventBusPipeline(processed_path)
    result = pipeline.run(verbose=True)

    # Сохраняем
    out_path = "output/pipeline_result.json"
    with open(out_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nСохранено: {out_path}")
    print(f"Общее время: {result['elapsed_s']}s")
    print(f"Решение Dispatcher: {result['dispatch']['action']}")
    
    # Выводим результаты семиотического анализа
    semiotic = result.get("semiotic", [])
    if semiotic:
        print(f"\n{'=' * 60}")
        print(f"СЕМИОТИЧЕСКИЙ АНАЛИЗ: {len(semiotic)} страниц")
        print(f"{'=' * 60}")
        for sr in semiotic[:5]:  # Показываем первые 5
            page_id = sr["page_id"]
            form = sr["classification"].get("primary_form", "?")
            rec_action = sr["recommendation"].get("recommended_action", "")[:100]
            confidence = sr["recommendation"].get("confidence", "?")
            urgency = sr["recommendation"].get("urgency", "?")
            print(f"\n  Стр. {page_id}: {form}")
            print(f"    Рекомендация: {rec_action}...")
            print(f"    Уверенность: {confidence}, Срочность: {urgency}")


if __name__ == "__main__":
    main()