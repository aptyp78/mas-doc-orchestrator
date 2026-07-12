"""Нормализация L1-выхода → Markdown + JSON-sidecar с эмбеддингами."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    pass


from src.agents.dashscope import ollama_embed


class Section(TypedDict):
    id: str
    level: int
    heading: str
    parent: str  # ROOT or S{N}
    line: int


def normalize_markdown(raw_text: str) -> str:
    """Преобразует сырой текст в чистый Markdown с иерархией."""
    lines = raw_text.strip().split("\n")
    md_lines = []
    prev_empty = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            md_lines.append("")
            prev_empty = True
            continue

        indent = len(line) - len(line.lstrip())
        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
        is_heading_pattern = (
            len(stripped) < 60
            and next_line
            and len(next_line) > len(stripped)
            and not stripped.startswith("•")
            and not stripped.startswith("-")
            and not re.match(r"^\d+[\.\s]", stripped)
        )

        if stripped.lower() in ["концепт", "концепция", "финальный концепт", "финальный тезис"]:
            md_lines.append(f"## {stripped}")
        elif re.match(r"^(почему|два этапа|этапы|финальный|ключевые)", stripped.lower()):
            md_lines.append(f"## {stripped}")
        elif is_heading_pattern and prev_empty:
            md_lines.append(f"## {stripped}")
        elif indent >= 4 and stripped[0].isalpha() and len(stripped) < 80:
            md_lines.append(f"### {stripped}")
        elif re.match(r"^\d+\s+\S", stripped) and not re.match(r"^\d+\s+[A-ZА-Я]", stripped):
            parts = re.split(r"\s{2,}", stripped, maxsplit=2)
            if len(parts) >= 2:
                num, title = parts[0], parts[1]
                rest = parts[2] if len(parts) > 2 else ""
                md_lines.append(f"{num}. **{title}** — {rest}")
            else:
                md_lines.append(stripped)
        elif re.match(r"^\d+\.\s", stripped):
            md_lines.append(stripped)
        elif stripped.startswith("•"):
            md_lines.append(f"- {stripped[1:].strip()}")
        else:
            md_lines.append(stripped)

        prev_empty = False

    return "\n".join(md_lines)


def extract_spans(text: str) -> list[dict]:
    """Извлекает спаны: числа + аббревиатуры."""
    spans = []
    sid = 0

    for m in re.finditer(r"\d+[\.,]?\d*\s*(?:руб|кВт|млрд|млн|тыс|%|₽|[A-Za-z]+)?", text):
        sid += 1
        spans.append(
            {
                "id": f"SP{sid}",
                "text": m.group(),
                "type": "number",
                "char_offset": m.start(),
                "char_length": m.end() - m.start(),
            }
        )

    abbr_pattern = (
        r"\b[A-ZА-Я]{2,8}\b|"
        r"\b(?:GPU|CPU|API|LLM|AI|NVIDIA|AMD|Intel|Huawei|Ascend|Biren|Cambricon|"
        r"Tesla|RTX|PCIe|NVMe|SSD|HDD|DMZ|WAN|LAN|SDLC|ДБО|ОПК|ПАК|ЦОД|ГОСТ|"
        r"CAPEX|SLA|OCR|MoE|SSM|GQA|KV|FFN|RoPE|BIB|АНО)\b"
    )
    for m in re.finditer(abbr_pattern, text):
        sid += 1
        spans.append(
            {
                "id": f"SP{sid}",
                "text": m.group(),
                "type": "entity",
                "char_offset": m.start(),
                "char_length": m.end() - m.start(),
            }
        )

    return spans


def extract_sections(md_text: str) -> list[Section]:
    """Извлекает структуру секций из Markdown."""
    sections: list[Section] = []
    lines = md_text.split("\n")
    # Use type: ignore because initial stack has int level but later dicts have str ids
    stack: list[dict[str, str | int]] = [{"id": "ROOT", "level": -1}]  # type: ignore[misc]

    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if not m:
            continue
        level = len(m.group(1))
        heading = m.group(2)
        sid: str = f"S{len(sections) + 1}"

        while stack and int(stack[-1]["level"]) >= level:
            stack.pop()
        parent = stack[-1]["id"] if stack else "ROOT"  # type: ignore[assignment]

        sections.append({"id": sid, "level": level, "heading": heading, "parent": parent, "line": i})  # type: ignore[misc, typeddict-item]
        stack.append({"id": f"S{len(sections) + 1}", "level": level})  # type: ignore[list-item]

    return sections


def normalize_document(
    name: str,
    raw_text: str,
    source: str = "unknown",
    output_dir: str = "/tmp/normalized",
    embed_model: str = "qwen3-embedding:8b",
) -> tuple[str, dict]:
    """Полный цикл нормализации: Markdown + JSON-sidecar с эмбеддингами."""
    os.makedirs(output_dir, exist_ok=True)

    # 1. Markdown
    md = normalize_markdown(raw_text)
    md_path = os.path.join(output_dir, f"{name}.md")
    with open(md_path, "w") as f:
        f.write(md)

    # 2. Секции
    sections = extract_sections(md)

    # 3. Спаны
    spans = extract_spans(md)

    # 4. Embeddings
    embeddings: dict[str, list[float]] = {}
    for sec in sections:
        lines_list = md.split("\n")
        start_line = int(sec["line"])
        end_line = len(lines_list)
        for j in range(start_line + 1, len(lines_list)):
            m = re.match(r"^(#{1,6})\s+", lines_list[j])
            if m and len(m.group(1)) <= int(sec["level"]):
                end_line = j
                break
        sec_text = "\n".join(lines_list[start_line:end_line]).strip()
        if sec_text:
            sid_key: str = sec["id"]
            embeddings[sid_key] = ollama_embed(sec_text, model=embed_model)[:8]

    for sp in spans[:5]:
        sp_text = str(sp["text"])
        embeddings[str(sp["id"])] = ollama_embed(sp_text, model=embed_model)[:8]

    # 5. JSON-sidecar
    doc_id = hashlib.md5(name.encode()).hexdigest()[:8]
    sidecar = {
        "doc_id": doc_id,
        "source": source,
        "name": name,
        "normalized_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "markdown_file": f"{name}.md",
        "stats": {
            "chars": len(md),
            "sections": len(sections),
            "spans": len(spans),
            "numbers": sum(1 for s in spans if s["type"] == "number"),
            "entities": sum(1 for s in spans if s["type"] == "entity"),
        },
        "sections": sections,
        "spans": spans,
        "embeddings": {k: v for k, v in embeddings.items()},
    }

    json_path = os.path.join(output_dir, f"{name}.meta.json")
    with open(json_path, "w") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)

    return md, sidecar
