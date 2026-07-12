#!/usr/bin/env python3
"""Запуск оркестратора на PDF-файле."""
import sys
import base64
import fitz
from src.orchestrator.engine import Orchestrator


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 scripts/run_orchestrator.py <путь к PDF>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    print(f"Загрузка: {pdf_path}")

    doc = fitz.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(dpi=200)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()
    doc.close()
    print(f"Страница: {page.rect.width:.0f}×{page.rect.height:.0f} px, base64: {len(img_b64)} символов")

    orch = Orchestrator(img_b64)
    result, confidence, history = orch.run()

    orch.save("output/orchestrator_result.json")
    print(f"\nСохранено: output/orchestrator_result.json")


if __name__ == "__main__":
    main()