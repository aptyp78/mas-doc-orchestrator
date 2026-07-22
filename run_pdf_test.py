#!/usr/bin/env python3
"""Простой тест PDF парсинга без зависимостей от Orchestrator."""
import sys
import os
import base64

# Ensure project root is in path
sys.path.insert(0, os.getcwd())

import fitz
from src.ingestion.format_detector import prepare_for_pipeline


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_pdf_test.py <file_path>")
        print("Supported formats: PDF, PPTX, DOCX, PNG, JPG, HTML, MD")
        sys.exit(1)

    input_path = sys.argv[1]

    # Use relative path from project root
    if not os.path.isabs(input_path):
        input_path = os.path.join(os.getcwd(), input_path)

    print(f"Input file: {input_path}")

    # Format Detector Agent: определяем формат и конвертируем если нужно
    print("\n[Format Detector Agent]")
    pdf_path = prepare_for_pipeline(input_path)
    print(f"Ready for pipeline: {pdf_path}")

    print(f"\n[PDF Test]")
    doc = fitz.open(pdf_path)
    if len(doc) == 0:
        print("Error: PDF empty")
        sys.exit(1)

    page = doc[0]
    rect = page.rect
    w, h = int(rect.width), int(rect.height)

    pix = page.get_pixmap(dpi=200)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()
    doc.close()

    print(f"Page: {w}×{h} px, base64: {len(img_b64)} chars")

    return w, h, len(img_b64)


if __name__ == "__main__":
    main()
