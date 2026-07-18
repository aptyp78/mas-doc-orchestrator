"""OCR2 Normalizer — PDF → DeepSeek OCR2 → structured blocks.

Заменяет цепочку Tesseract → Cloud vision → Local vision.
DeepSeek OCR2 (локальный, MLX на Apple Silicon) даёт:
- markdown со структурой (sub_title, text, image)
- координаты каждого блока (x, y, w, h)
- 1-3 секунды на страницу

Выход: структурированные блоки для подачи в семиотический конвейер.
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fitz

# MCP DeepSeek OCR2 endpoint (локальный HTTP)
OCR2_ENDPOINT = "http://127.0.0.1:5100/call"  # стандартный порт MCP


@dataclass
class Block:
    """Структурный блок страницы."""
    block_type: str  # sub_title, text, image
    content: str
    bbox: list[int]  # [x, y, w, h] или [x1, y1, x2, y2]
    page_num: int = 0

    @property
    def area(self) -> float:
        if len(self.bbox) == 4:
            return abs(self.bbox[2] - self.bbox[0]) * abs(self.bbox[3] - self.bbox[1])
        return 0.0

    @property
    def is_visual(self) -> bool:
        """Визуальный блок (image) — требует VL-модели."""
        return self.block_type == "image"

    @property
    def is_textual(self) -> bool:
        """Текстовый блок — не требует VL."""
        return self.block_type in ("text", "sub_title")


@dataclass
class PageLayout:
    """Размеченная страница."""
    page_num: int
    blocks: list[Block] = field(default_factory=list)
    raw_markdown: str = ""
    ocr_time_s: float = 0.0

    @property
    def text_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.is_textual]

    @property
    def image_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.is_visual]

    @property
    def has_visual_content(self) -> bool:
        return len(self.image_blocks) > 0

    @property
    def dominant_block_type(self) -> str:
        """Доминирующий тип блоков по площади."""
        areas: dict[str, float] = {}
        for b in self.blocks:
            areas[b.block_type] = areas.get(b.block_type, 0) + b.area
        if not areas:
            return "text"
        return max(areas, key=areas.get)

    def get_text_content(self) -> str:
        """Весь текст страницы (без image-блоков)."""
        return "\n".join(b.content for b in self.text_blocks if b.content.strip())

    def get_image_bboxes(self) -> list[list[int]]:
        """Bbox'ы image-блоков для VL-модели."""
        return [b.bbox for b in self.image_blocks]


def _parse_ocr2_markdown(markdown: str, page_num: int) -> list[Block]:
    """Парсит markdown от DeepSeek OCR2 в структурированные блоки.

    Формат OCR2:
    <|ref|>block_type<|/ref|><|det|>[[x1,y1,x2,y2],...]<|/det|>
    content
    """
    blocks = []
    # Паттерн: <|ref|>type<|/ref|><|det|>[[coords]]<|/det|>\ncontent
    pattern = re.compile(
        r'<\|ref\|>(.*?)<\|/ref\|>\s*<\|det\|>\[(.*?)\]\s*<\|/det\|>\s*\n(.*?)(?=\n<\|ref\|>|$)',
        re.DOTALL,
    )

    for match in pattern.finditer(markdown):
        block_type = match.group(1).strip()
        coords_str = match.group(2).strip()
        content = match.group(3).strip()

        # Парсим координаты: [[x1,y1,x2,y2]] или [[x1,y1,x2,y2],[x1,y1,x2,y2]]
        bboxes = []
        for coord_match in re.finditer(r'\[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\]', coords_str):
            bboxes.append([int(coord_match.group(i)) for i in range(1, 5)])

        bbox = bboxes[0] if bboxes else [0, 0, 0, 0]

        blocks.append(Block(
            block_type=block_type,
            content=content,
            bbox=bbox,
            page_num=page_num,
        ))

    return blocks


def ocr_page(pdf_path: str, page_num: int, dpi: int = 200) -> PageLayout:
    """Распознаёт одну страницу через DeepSeek OCR2.

    Процесс:
    1. Рендерит страницу PDF в PNG
    2. Вызывает DeepSeek OCR2 (MCP)
    3. Парсит результат в структурированные блоки
    """
    t0 = time.time()

    # Рендер страницы в PNG
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    img_bytes = pix.tobytes("png")
    doc.close()

    # Сохраняем во временный файл
    tmp_path = f"/tmp/ocr2_page_{page_num + 1}.png"
    with open(tmp_path, "wb") as f:
        f.write(img_bytes)

    # Вызов DeepSeek OCR2 через MCP
    try:
        data = json.dumps({
            "file_path": tmp_path,
            "mode": "markdown",
        }).encode()
        req = urllib.request.Request(
            OCR2_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            markdown = result.get("result", "")
            ocr_time = result.get("duration_seconds", 0)
    except Exception:
        # Fallback: возвращаем пустую разметку
        markdown = ""
        ocr_time = 0

    blocks = _parse_ocr2_markdown(markdown, page_num + 1)
    elapsed = time.time() - t0

    return PageLayout(
        page_num=page_num + 1,
        blocks=blocks,
        raw_markdown=markdown,
        ocr_time_s=ocr_time,
    )


def ocr_document(pdf_path: str, dpi: int = 200, max_pages: int | None = None) -> dict[int, PageLayout]:
    """Распознаёт все страницы документа через DeepSeek OCR2."""
    doc = fitz.open(pdf_path)
    total = len(doc) if max_pages is None else min(len(doc), max_pages)
    doc.close()

    print(f"OCR2: {total} pages...")
    t0 = time.time()
    layouts = {}

    for i in range(total):
        layout = ocr_page(pdf_path, i, dpi)
        layouts[i + 1] = layout
        n_text = len(layout.text_blocks)
        n_img = len(layout.image_blocks)
        print(f"  p{i+1}: {n_text}t/{n_img}i blocks — {layout.ocr_time_s:.1f}s (OCR2)")

    total_elapsed = time.time() - t0
    total_ocr = sum(l.ocr_time_s for l in layouts.values())
    print(f"OCR2 done: {total_elapsed:.1f}s wall, {total_ocr:.1f}s OCR2")

    return layouts