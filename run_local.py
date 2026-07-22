#!/usr/bin/env python3
"""Запуск оркестратора на PDF-файле с локальной интеграцией."""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.getcwd())

from fitz import open as fitz_open
import base64

from src.orchestrator.engine import Orchestrator
from src.ingestion.format_detector import prepare_for_pipeline


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 run_local.py <путь к файлу>")
        print("Поддерживаемые форматы: PDF, PPTX, DOCX, PNG, JPG, HTML, MD")
        sys.exit(1)

    input_path = sys.argv[1]

    # Use relative path from project root
    if not os.path.isabs(input_path):
        input_path = os.path.join(os.getcwd(), input_path)

    print(f"Входной файл: {input_path}")

    # Format Detector Agent: определяем формат и конвертируем если нужно
    print("\n[Format Detector Agent]")
    pdf_path = prepare_for_pipeline(input_path)
    print(f"Готов для pipeline: {pdf_path}")

    print(f"\n[Pipeline]")
    doc = fitz_open(pdf_path)
    if len(doc) == 0:
        print("Ошибка: PDF пустой")
        sys.exit(1)

    page = doc[0]
    rect = page.rect
    w, h = int(rect.width), int(rect.height)

    pix = page.get_pixmap(dpi=200)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()
    doc.close()

    print(f"Страница: {w}×{h} px, base64: {len(img_b64)} символов")

    orch = Orchestrator(img_b64)
    result, confidence, history = orch.run()

    orch.save("output/orchestrator_result.json")
    print(f"\nСохранено: output/orchestrator_result.json")


if __name__ == "__main__":
    main()
