#!/usr/bin/env python3
"""Простой тест PDF парсинга без зависимостей от Orchestrator."""
import sys
import os
import base64

# Ensure project root is in path
sys.path.insert(0, os.getcwd())

import fitz


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_pdf_test.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    # Use relative path from project root
    if not os.path.isabs(pdf_path):
        pdf_path = os.path.join(os.getcwd(), pdf_path)

    print(f"Loading: {pdf_path}")

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
