#!/usr/bin/env python3
"""Запуск оркестратора на PDF-файле с локальной интеграцией."""
import sys
import os
import base64
import fitz

# path setup - insert project root to allow package-style imports
import __main__
script_dir = getattr(__main__, '__file__', None)
if script_dir:
    project_root = os.path.dirname(os.path.abspath(script_dir))
else:
    # Fallback when run as main directly
    project_root = os.getcwd()
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.orchestrator.engine import Orchestrator


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 run_local.py <путь к PDF>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    print(f"Загрузка: {pdf_path}")

    doc = fitz.open(pdf_path)
    if len(doc) == 0:
        print("Ошибка: PDF пустой")
        sys.exit(1)
    
    page = None

    # Try to get any valid page using direct iteration
    try:
        for p in doc:
            if p is not None:
                r = p.rect  # Test access
                page = p
                break
    except Exception:
        pass

    # Fallback to direct indexing if iteration failed
    if page is None and len(doc) > 0:
        try:
            page = doc[0]
            _ = page.rect  # Verify accessibility
        except Exception:
            pass

    if page is None:
        print("Ошибка: не удалось получить страницу")
        sys.exit(1)

    # Final verification before use - extract values to avoid f-string bug in pymupdf
    r = page.rect
    w, h = int(r.width), int(r.height)
    
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
