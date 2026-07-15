"""Уровень 1: Семиотический классификатор знаковых форм.

Определяет, в какой знаковой форме зафиксирована мысль на странице:
- narrative (текст)
- venn (диаграмма множеств)
- table (таблица)
- diagram (блок-схема, процесс)
- list (список)
- mixed (несколько форм)

Использует qwen3-vl:30b для классификации страницы.
"""

from __future__ import annotations

import base64
import json
import urllib.request

import fitz

from src.utils.config import OLLAMA_LOCAL_BASE

VISION_MODEL = "qwen3-vl:30b"

SEMIOTIC_PROMPT = """[РОЛЬ] Семиотический классификатор
[ПРЕДМЕТ] Изображение страницы документа
[ЗАДАЧА] Определи знаковую форму, в которой зафиксирована мысль на этой странице
[ПРАВИЛА]
- discursive: сплошной текст, абзацы — дискурсивно-линейная развертка смысла (аргументация, нарратив)
- topology: круги, пересекающиеся множества, зоны интересов — топологическая схема пересекающихся пространств (конфликтный анализ, картирование)
- matrix: строки и столбцы, ячейки — матричная структура перекрестной классификации (систематизация)
- hierarchy: пирамида, уровни, ярусы — иерархическая структура целе-средств (стратегическое планирование)
- spatial: географическая карта, территория — пространственно-локализующая схема (ситуационный анализ)
- enumeration: маркированный/нумерованный список — структура параллельного перечисления
- dynamics: график, кривая, оси координат — схема функционально-временной динамики (тренд-анализ)
- mixed: комбинация двух и более форм
- empty: пустая страница или только номер
[ОГРАНИЧЕНИЕ] Только классификация формы. Не интерпретируй содержание.

Формат: JSON
{
  "primary_form": "discursive|topology|matrix|hierarchy|spatial|enumeration|dynamics|mixed|empty",
  "secondary_forms": ["..."],
  "confidence": "HIGH|MEDIUM|LOW",
  "rationale": "краткое обоснование"
}"""


def classify_page(page: fitz.Page, dpi: int = 150) -> dict:
    """Классифицирует знаковую форму страницы."""
    pix = page.get_pixmap(dpi=dpi)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()

    data = json.dumps({
        "model": VISION_MODEL,
        "prompt": SEMIOTIC_PROMPT,
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

    return {"primary_form": "discursive", "secondary_forms": [], "confidence": "LOW", "rationale": "parse_failed"}


def classify_document(pdf_path: str, dpi: int = 150) -> dict:
    """Классифицирует все страницы документа по знаковым формам."""
    doc = fitz.open(pdf_path)
    pages = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        classification = classify_page(page, dpi=dpi)
        pages.append({
            "page_id": page_num + 1,
            "width": int(page.rect.width),
            "height": int(page.rect.height),
            "primary_form": classification.get("primary_form", "narrative"),
            "secondary_forms": classification.get("secondary_forms", []),
            "confidence": classification.get("confidence", "LOW"),
            "rationale": classification.get("rationale", ""),
        })

    doc.close()

    # Статистика форм
    form_counts = {}
    for p in pages:
        f = p["primary_form"]
        form_counts[f] = form_counts.get(f, 0) + 1

    return {
        "pages": pages,
        "stats": {
            "total_pages": len(pages),
            "form_distribution": form_counts,
        },
    }