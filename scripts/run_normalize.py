#!/usr/bin/env python3
"""Запуск нормализатора на текстовом файле."""
import sys
from src.pipeline.normalizer import normalize_document


def main():
    if len(sys.argv) < 2:
        print("Использование: python3 scripts/run_normalize.py <путь к .txt>")
        sys.exit(1)

    txt_path = sys.argv[1]
    with open(txt_path) as f:
        raw_text = f.read()

    name = txt_path.rsplit("/", 1)[-1].replace(".txt", "")
    md, sidecar = normalize_document(name, raw_text, source=txt_path, output_dir="output/normalized")

    print(f"\nMarkdown: {len(md)} chars, {sidecar['stats']['sections']} секций, {sidecar['stats']['spans']} спанов")
    print(f"Сохранено: output/normalized/{name}.md + output/normalized/{name}.meta.json")


if __name__ == "__main__":
    main()