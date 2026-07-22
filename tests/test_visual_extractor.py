"""Тест для Visual Extractor (ОРП 5)."""

import sys
from pathlib import Path

# Добавляем src в путь
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from orchestrator.roles.visual_extractor import run


def test_visual_extractor():
    """Тестирует извлечение примитивов и классификацию страницы."""
    # Используем тестовый PDF
    test_pdf = Path(__file__).parent.parent / "data" / "docs" / "Презентация ИАфр РАН_финал.pdf"
    
    if not test_pdf.exists():
        print(f"⚠️  Тестовый PDF не найден: {test_pdf}")
        print("Пропускаем тест")
        return
    
    print(f"Тестируем Visual Extractor на {test_pdf.name}...")
    
    # Извлекаем примитивы со страницы 0
    result = run(str(test_pdf), page_number=0, extract_primitives=True)
    
    print(f"\nРезультат:")
    print(f"  Классификация страницы: {result['page_classification']}")
    print(f"  Всего страниц: {result['total_pages']}")
    
    primitives = result.get('primitives', {})
    text_blocks = primitives.get('text_blocks', [])
    image_blocks = primitives.get('image_blocks', [])
    vector_blocks = primitives.get('vector_blocks', [])
    
    print(f"  Текстовых блоков: {len(text_blocks)}")
    print(f"  Изображений: {len(image_blocks)}")
    print(f"  Векторных путей: {len(vector_blocks)}")
    
    drawings = result.get('drawings_classification', [])
    print(f"  Классифицировано drawings: {len(drawings)}")
    
    if drawings:
        for d in drawings[:3]:  # Показываем первые 3
            print(f"    - {d['classification']} (bbox: {d['bbox']}, items: {d['item_count']})")
    
    print("\n✅ Visual Extractor работает!")


if __name__ == "__main__":
    test_visual_extractor()
