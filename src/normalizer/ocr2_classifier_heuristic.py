"""L1 Classifier — эвристическая версия (без Ollama).

Быстрая классификация image-блоков на основе:
- Размера bbox (площадь)
- Позиции на странице
- Контекста (наличие числовых данных в surrounding text)

Не требует вызова LLM — работает мгновенно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ImageClassification:
    """Результат классификации image-блока."""
    needs_vl: bool
    visual_form: str  # bar_chart | map | hierarchy | venn | logo | decorative
    rationale: str
    confidence: float


def classify_image_block_heuristic(bbox: list[int], surrounding_text: str,
                                   page_form_hint: str = "unknown",
                                   page_width: int = 1000, page_height: int = 1000) -> ImageClassification:
    """Эвристическая классификация image-блока."""

    # Размер блока
    x1, y1, x2, y2 = bbox if len(bbox) == 4 else [0, 0, 0, 0]
    width = x2 - x1
    height = y2 - y1
    area = width * height
    page_area = page_width * page_height
    area_ratio = area / page_area if page_area > 0 else 0

    # Позиция
    is_corner = (x1 < 100 and y1 < 100) or (x1 > page_width - 100 and y1 < 100) or \
                (x1 < 100 and y1 > page_height - 100) or (x1 > page_width - 100 and y1 > page_height - 100)

    # Контекст: наличие числовых данных
    has_numbers = bool(re.search(r'\d+[%°]|\d+\.\d+|\d{2,}', surrounding_text))
    has_keywords = any(kw in surrounding_text.lower() for kw in [
        'диаграмм', 'карт', 'схем', 'график', 'пирамид', 'иерарх',
        'венн', 'пересечен', 'множеств', 'ресурс', 'минерал', 'золот',
        'доля', 'процент', 'объём', 'динамика', 'тренд'
    ])

    # Правила классификации
    if area_ratio < 0.01 and is_corner:
        # Маленький блок в углу — логотип
        return ImageClassification(
            needs_vl=False,
            visual_form="logo",
            rationale=f"Small corner block ({width}x{height}, {area_ratio:.3f} of page)",
            confidence=0.95
        )

    if area_ratio < 0.02 and not has_numbers and not has_keywords:
        # Маленький блок без числовых данных — декоративный
        return ImageClassification(
            needs_vl=False,
            visual_form="decorative",
            rationale=f"Small block without data context ({width}x{height})",
            confidence=0.85
        )

    if area_ratio > 0.1 and has_keywords:
        # Большой блок с ключевыми словами — нужна VL
        if any(kw in surrounding_text.lower() for kw in ['карт', 'регион', 'стран']):
            visual_form = "map"
        elif any(kw in surrounding_text.lower() for kw in ['пирамид', 'иерарх', 'уровен']):
            visual_form = "hierarchy"
        elif any(kw in surrounding_text.lower() for kw in ['венн', 'пересечен', 'множеств']):
            visual_form = "venn"
        else:
            visual_form = "bar_chart"

        return ImageClassification(
            needs_vl=True,
            visual_form=visual_form,
            rationale=f"Large block ({area_ratio:.2f} of page) with data keywords",
            confidence=0.90
        )

    if has_numbers and area_ratio > 0.05:
        # Блок с числовыми данными — нужна VL
        return ImageClassification(
            needs_vl=True,
            visual_form="bar_chart",
            rationale=f"Block with numbers ({width}x{height}, {area_ratio:.3f})",
            confidence=0.80
        )

    # По умолчанию — не нужна VL
    return ImageClassification(
        needs_vl=False,
        visual_form="decorative",
        rationale=f"Default: area_ratio={area_ratio:.3f}, has_numbers={has_numbers}",
        confidence=0.60
    )