"""L1 Classifier Agent — решение «нужен ли VL?» для image-блоков OCR2.

Принимает image-блок и контекст страницы, возвращает:
- needs_vl: true/false
- visual_form: bar_chart | map | hierarchy | venn | logo | decorative
- rationale: обоснование решения

Использует qwen3.6:35b (текстовая модель, не VL).
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"


@dataclass
class ImageClassification:
    """Результат классификации image-блока."""
    needs_vl: bool
    visual_form: str  # bar_chart | map | hierarchy | venn | logo | decorative
    rationale: str
    confidence: float  # 0.0-1.0


def _call_ollama(prompt: str, max_tokens: int = 512) -> str:
    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.1, "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat", data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["message"]["content"]


def _parse_json(text: str) -> dict:
    try:
        j1, j2 = text.find("{"), text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass
    return {}


class L1ClassifierAgent:
    """Классификатор image-блоков: нужен ли VL?"""

    PROMPT = """[РОЛЬ] Классификатор визуальных блоков документа
[ПРЕДМЕТ] Image-блок из OCR2 + контекст страницы
[ЗАДАЧА] Определи, несёт ли image-блок семантическую нагрузку, недоступную текстовому OCR
[ПРАВИЛА]
1. needs_vl = true, если блок содержит данные, которые нельзя извлечь текстом:
   - bar_chart: столбчатая/линейная диаграмма с числовыми данными
   - map: географическая карта с регионами
   - hierarchy: пирамида, иерархическая схема
   - venn: диаграмма Венна, пересекающиеся множества
2. needs_vl = false, если блок:
   - logo: логотип организации
   - decorative: декоративный элемент, фон, разделитель
   - photo: фотография без числовых данных
3. Оцени confidence: 0.0-1.0
[ОГРАНИЧЕНИЕ] Если сомневаешься — needs_vl = true (лучше лишнее VL, чем пропуск данных).

Формат: JSON
{{
  "needs_vl": true/false,
  "visual_form": "bar_chart|map|hierarchy|venn|logo|decorative|photo",
  "rationale": "string",
  "confidence": 0.0-1.0
}}

## IMAGE-БЛОК
- bbox: {bbox}
- размер: {width}x{height} px

## КОНТЕКСТ СТРАНИЦЫ
{surrounding_text}

## ПОДСКАЗКА ФОРМЫ СТРАНИЦЫ
{page_form_hint}"""

    def classify(self, bbox: list[int], surrounding_text: str,
                 page_form_hint: str = "unknown") -> ImageClassification:
        """Классифицирует image-блок."""
        width = bbox[2] - bbox[0] if len(bbox) >= 4 else 0
        height = bbox[3] - bbox[1] if len(bbox) >= 4 else 0

        prompt = self.PROMPT.format(
            bbox=bbox,
            width=width,
            height=height,
            surrounding_text=surrounding_text[:500],
            page_form_hint=page_form_hint,
        )

        result = _parse_json(_call_ollama(prompt, max_tokens=512))

        return ImageClassification(
            needs_vl=result.get("needs_vl", True),
            visual_form=result.get("visual_form", "photo"),
            rationale=result.get("rationale", ""),
            confidence=result.get("confidence", 0.5),
        )


def classify_image_block(bbox: list[int], surrounding_text: str,
                         page_form_hint: str = "unknown") -> ImageClassification:
    """Удобная функция-обёртка."""
    agent = L1ClassifierAgent()
    return agent.classify(bbox, surrounding_text, page_form_hint)