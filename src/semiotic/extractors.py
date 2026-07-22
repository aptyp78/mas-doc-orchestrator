"""Уровень 2: Схемные экстракторы.

Для каждой знаковой формы — свой экстрактор, извлекающий абстрактный шаблон схемы.
"""

from __future__ import annotations

import base64
import json
import urllib.request

import fitz

from src.utils.config import OLLAMA_LOCAL_BASE
from src.utils.prompt_loader import load_prompt

VISION_MODEL = "qwen3-vl:30b"

# ═══════════════════════════════════════════════════════════════
# Venn Extractor
# ═══════════════════════════════════════════════════════════════

VENN_PROMPT = load_prompt("semiotic/extractors_venn")


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


# ═══════════════════════════════════════════════════════════════
# Hierarchy Extractor
# ═══════════════════════════════════════════════════════════════

HIERARCHY_PROMPT = load_prompt("semiotic/extractors_hierarchy")


def extract_hierarchy(page: fitz.Page, dpi: int = 150) -> dict:
    pix = page.get_pixmap(dpi=dpi)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()
    data = json.dumps({"model": VISION_MODEL, "prompt": HIERARCHY_PROMPT, "images": [img_b64], "stream": False}).encode()
    req = urllib.request.Request(f"{OLLAMA_LOCAL_BASE}/api/generate", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = json.loads(resp.read())
        result_text = raw["response"]
    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1: return json.loads(result_text[j1:j2])
    except (json.JSONDecodeError, KeyError): pass
    return {"levels": [], "error": "parse_failed"}


# ═══════════════════════════════════════════════════════════════
# Matrix Extractor
# ═══════════════════════════════════════════════════════════════

MATRIX_PROMPT = load_prompt("semiotic/extractors_matrix")


def extract_matrix(page: fitz.Page, dpi: int = 150) -> dict:
    pix = page.get_pixmap(dpi=dpi)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()
    data = json.dumps({"model": VISION_MODEL, "prompt": MATRIX_PROMPT, "images": [img_b64], "stream": False}).encode()
    req = urllib.request.Request(f"{OLLAMA_LOCAL_BASE}/api/generate", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = json.loads(resp.read())
        result_text = raw["response"]
    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1: return json.loads(result_text[j1:j2])
    except (json.JSONDecodeError, KeyError): pass
    return {"columns": [], "rows": [], "error": "parse_failed"}


# ═══════════════════════════════════════════════════════════════
# Enumeration Extractor
# ═══════════════════════════════════════════════════════════════

ENUMERATION_PROMPT = load_prompt("semiotic/extractors_enumeration")


def extract_enumeration(page: fitz.Page, dpi: int = 150) -> dict:
    pix = page.get_pixmap(dpi=dpi)
    img_b64 = base64.b64encode(pix.tobytes("png")).decode()
    data = json.dumps({"model": VISION_MODEL, "prompt": ENUMERATION_PROMPT, "images": [img_b64], "stream": False}).encode()
    req = urllib.request.Request(f"{OLLAMA_LOCAL_BASE}/api/generate", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        raw = json.loads(resp.read())
        result_text = raw["response"]
    try:
        j1, j2 = result_text.find("{"), result_text.rfind("}") + 1
        if j1 >= 0 and j2 > j1: return json.loads(result_text[j1:j2])
    except (json.JSONDecodeError, KeyError): pass
    return {"items": [], "error": "parse_failed"}