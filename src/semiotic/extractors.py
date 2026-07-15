"""Уровень 2: Схемные экстракторы.

Для каждой знаковой формы — свой экстрактор, извлекающий абстрактный шаблон схемы.
"""

from __future__ import annotations

import base64
import json
import urllib.request

import fitz

from src.utils.config import OLLAMA_LOCAL_BASE

VISION_MODEL = "qwen3-vl:30b"

# ═══════════════════════════════════════════════════════════════
# Venn Extractor
# ═══════════════════════════════════════════════════════════════

VENN_PROMPT = """[РОЛЬ] Экстрактор Venn-диаграммы
[ПРЕДМЕТ] Страница с диаграммой Венна (пересекающиеся множества)
[ЗАДАЧА] Извлеки структуру диаграммы как схему множеств
[ПРАВИЛА]
1. Перечисли ВСЕ множества (круги) — кто/что они представляют
2. Для каждого множества — перечисли ВСЕ элементы внутри
3. Перечисли ВСЕ зоны пересечения — какие множества пересекаются и какие элементы в пересечении
4. Выдели центральную зону (пересечение всех) — если есть
5. Извлеки ВСЕ цифры, проценты, метрики со страницы
6. Извлеки вывод/заголовок/тезис страницы
[ОГРАНИЧЕНИЕ] Не интерпретируй. Извлекай ВСЕ элементы, ничего не пропускай.

Формат: JSON
{
  "sets": [
    {"name": "string", "elements": ["elem1", "elem2", ...], "metrics": {"key": "value"}}
  ],
  "intersections": [
    {"sets": ["name1", "name2"], "elements": ["elem1", ...], "label": "string"}
  ],
  "center": {"label": "string", "elements": [], "description": "string"},
  "page_title": "string",
  "conclusion": "string",
  "all_metrics": [{"label": "string", "value": "string"}],
  "element_count": 0
}"""


def extract_venn(page: fitz.Page, dpi: int = 150) -> dict:
    """Извлекает структуру Venn-диаграммы."""
    pix = page.get_pixmap(dpi=dpi)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()

    data = json.dumps({
        "model": VISION_MODEL,
        "prompt": VENN_PROMPT,
        "images": [img_b64],
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = json.loads(resp.read())
        result_text = raw["response"]

    try:
        json_start = result_text.find("{")
        json_end = result_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(result_text[json_start:json_end])
    except (json.JSONDecodeError, KeyError):
        pass

    return {"sets": [], "intersections": [], "center": {}, "error": "parse_failed"}