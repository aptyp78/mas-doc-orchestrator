#!/usr/bin/env python3
"""Запуск ролевого пайплайна (7 ОРП) на PDF-файле."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.orchestrator.roles.dispatcher import EventBusPipeline


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 run_pipeline.py <путь к PDF>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.isabs(pdf_path):
        pdf_path = os.path.join(os.getcwd(), pdf_path)

    print(f"Загрузка: {pdf_path}")

    pipeline = EventBusPipeline(pdf_path)
    result = pipeline.run(verbose=True)

    # Сохраняем
    out_path = "output/pipeline_result.json"
    with open(out_path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nСохранено: {out_path}")
    print(f"Общее время: {result['elapsed_s']}s")
    print(f"Решение Dispatcher: {result['dispatch']['action']}")


if __name__ == "__main__":
    main()