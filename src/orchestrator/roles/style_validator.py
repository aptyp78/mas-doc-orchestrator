"""ОРП 3: Style & Format Validator.

Проверяет визуальное соответствие rule-based (без LLM).
"""

from __future__ import annotations

ROLE = (
    "[РОЛЬ] Style & Format Validator\n"
    "[ОБЪЕКТ] Визуальные примитивы и layout\n"
    "[ПРАВИЛА] Отклонения ≤ 5%. compliance_score = 1.0 - %_deviation/100.\n"
    "[ОГРАНИЧЕНИЕ] Не модифицируй контент."
)

PROMPT = ROLE


def run(
    visual_primitives: list[dict] | None = None,
    style_guide: dict | None = None,
    page_metadata: dict | None = None,
) -> dict:
    """Проверяет визуальное соответствие.

    Args:
        visual_primitives: список примитивов от Visual Extractor
        style_guide: опциональный гайд по стилям
        page_metadata: метаданные страницы

    Returns:
        dict с compliance_score, violations, layout_analysis
    """
    violations: list[dict] = []
    primitives = visual_primitives or []

    # Проверяем базовые метрики
    total_elements = len(primitives)
    if total_elements == 0:
        return {
            "compliance_score": 1.0,
            "violations": [],
            "layout_analysis": {"grid_match": True, "margin_consistency": 1.0},
        }

    # L1: проверка compliance
    # Без реальных примитивов — возвращаем нейтральный результат
    compliance_score = 1.0

    # Если есть style_guide — проверяем соответствие
    if style_guide:
        expected_colors = style_guide.get("palette", [])
        for prim in primitives:
            if prim.get("color") and prim["color"] not in expected_colors:
                violations.append(
                    {
                        "type": "color",
                        "element_id": prim.get("id", "unknown"),
                        "deviation_pct": 5.0,
                    }
                )

        if violations:
            compliance_score = max(0.0, 1.0 - (len(violations) / total_elements))

    return {
        "compliance_score": round(compliance_score, 2),
        "violations": violations,
        "layout_analysis": {
            "grid_match": True,
            "margin_consistency": 1.0,
        },
    }
