"""ОРП 4: Iteration & SLA Dispatcher.

3-стадийная архитектура:
  Стадия 1: Нормализация (L0) → Universal Representation
  Стадия 2: Доменная принадлежность (SMD) → Domain-Tagged Repr.
  Стадия 3: Анализ + Преобразование → Structured Knowledge Graph
"""

from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from src.normalizer.pdf_normalizer import normalize
from src.orchestrator.domain_analyzer import detect_domain
from src.utils.config import OLLAMA_LOCAL_BASE

ROLE = (
    "[РОЛЬ] Iteration & SLA Dispatcher\n"
    "[ОБЪЕКТ] Состояние системы MAS Orchestrator\n"
    "[ПРАВИЛА] threshold = base + class_weight * (1 - gap_ratio).\n"
    "          max_iterations = 2 deep + 1 heuristic.\n"
    "          Действия: ITERATE | FALLBACK | TERMINATE.\n"
    "[ОГРАНИЧЕНИЕ] Не анализируй контент документа."
)

PROMPT_TEMPLATE = (
    "{role}\n\n"
    "Метрики: {metrics}\n"
    "Конфиг: {config}\n\n"
    "Выдай решение как JSON с полями:\n"
    "- action: ITERATE | FALLBACK | TERMINATE\n"
    "- updated_thresholds: {{confidence_target, SLA_remaining_ms}}\n"
    "- routing_map: {{role_name: trigger_type}}\n"
    "- reason: string"
)

MODEL = "qwen3.6:35b"

# Веса классов документов
CLASS_WEIGHTS = {
    "text_only": 0.75,
    "mixed_text_vector": 0.80,
    "mixed_text_image": 0.82,
    "complex_diagram": 0.88,
}


def run(
    system_metrics: dict,
    max_iterations: int = 3,
    base_sla_seconds: int = 300,
    doc_class: str = "mixed_text_vector",
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> dict:
    """Принимает решение о следующем действии."""
    config = {
        "max_iterations": max_iterations,
        "base_SLA_seconds": base_sla_seconds,
        "class_weights": CLASS_WEIGHTS,
        "doc_class": doc_class,
    }

    prompt = PROMPT_TEMPLATE.format(
        role=ROLE,
        metrics=json.dumps(system_metrics, ensure_ascii=False),
        config=json.dumps(config, ensure_ascii=False),
    )

    data = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
    ).encode()

    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = json.loads(resp.read())
        result_text = raw["message"]["content"]

    try:
        json_start = result_text.find("{")
        json_end = result_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(result_text[json_start:json_end])
            return {
                "action": parsed.get("action", "FALLBACK"),
                "updated_thresholds": parsed.get("updated_thresholds", {}),
                "routing_map": parsed.get("routing_map", {}),
                "reason": parsed.get("reason", ""),
                "raw_output": result_text,
            }
    except (json.JSONDecodeError, KeyError):
        pass

    return {
        "action": "FALLBACK",
        "updated_thresholds": {},
        "routing_map": {},
        "reason": "failed_to_parse_dispatcher_output",
        "raw_output": result_text,
    }


def _build_text_for_disambiguation(universal_repr: dict, max_chars: int = 3000) -> str:
    """Строит текст для Semantic Disambiguator из Universal Representation.

    Ограничивает общий объём текста, чтобы не перегружать LLM.
    """
    pages = universal_repr.get("pages", [])
    page_texts = []
    total = 0
    for page in pages:
        text_elements = [
            e["content"] for e in page.get("elements", [])
            if e["type"] in ("text", "ocr_text")
        ]
        if text_elements:
            chunk = " ".join(text_elements)[:500]
            page_texts.append(chunk)
            total += len(chunk)
            if total >= max_chars:
                break
        elif page.get("zones"):
            zone_texts = [z.get("label", "") for z in page["zones"].get("zones", []) if "text" in z.get("type", "")]
            if zone_texts:
                chunk = " ".join(zone_texts)[:500]
                page_texts.append(chunk)
                total += len(chunk)
                if total >= max_chars:
                    break
    if not page_texts:
        page_texts = ["[Страница не содержит текста]"]
    return json.dumps({"pages": page_texts}, ensure_ascii=False)


def _extract_primitives_for_graph(universal_repr: dict, max_primitives: int = 30) -> list[dict]:
    """Извлекает примитивы из Universal Representation для Graph Builder.

    Ограничивает количество примитивов, чтобы не перегружать LLM.
    """
    primitives = []
    for page in universal_repr.get("pages", []):
        for elem in page.get("elements", []):
            primitives.append({
                "type": elem["type"],
                "bbox": elem["bbox"],
                "content": (elem.get("content", "") or "")[:200],  # обрезаем
                "page_id": page["page_id"],
            })
    return primitives[:max_primitives]


class Pipeline:
    """3-стадийный пайплайн: Нормализация → Домен → Анализ."""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.start_time = time.time()
        self.history: list[dict] = []

    def _elapsed(self) -> float:
        return time.time() - self.start_time

    def run(self, verbose: bool = True) -> dict:
        from src.orchestrator.roles import (
            context_resolver,
            graph_builder,
            metadata_extractor,
            semantic_disambiguator,
            style_validator,
        )

        if verbose:
            print("=" * 60)
            print("MAS PIPELINE: 3 стадии (Нормализация → Домен → Анализ)")
            print("=" * 60)

        # ═══════════════════════════════════════════════════════════
        # Стадия 1: Нормализация (L0) → Universal Representation
        # ═══════════════════════════════════════════════════════════
        if verbose:
            print("\n── Стадия 1: Нормализация ──")
        universal = normalize(self.pdf_path)
        self.history.append({"role": "normalizer", "output": universal})
        if verbose:
            stats = universal["stats"]
            print(f"  Страниц: {stats['total_pages']}, типы: {stats['page_types']}")

        # ═══════════════════════════════════════════════════════════
        # Стадия 2: Доменная принадлежность (SMD)
        # ═══════════════════════════════════════════════════════════
        if verbose:
            print("\n── Стадия 2: Доменная принадлежность (SMD) ──")
        domain_info = detect_domain(universal)
        self.history.append({"role": "domain_analyzer", "output": domain_info})
        if verbose:
            print(f"  Домены: {', '.join(d['domain'] for d in domain_info.get('domains', []))}")
            print(f"  Основной: {domain_info['primary_domain']}")
            print(f"  Glossaries: {', '.join(domain_info['glossaries_to_use'])}")

        # ═══════════════════════════════════════════════════════════
        # Стадия 3: Анализ + Преобразование
        # ═══════════════════════════════════════════════════════════
        if verbose:
            print("\n── Стадия 3: Анализ + Преобразование ──")

        # Metadata Extractor (работает на сыром PDF — не зависит от Universal Repr)
        if verbose:
            print("\n  [3a] Metadata Extractor...")
        meta = metadata_extractor.run(self.pdf_path)
        self.history.append({"role": "metadata_extractor", "output": meta})
        if verbose:
            print(f"    Атрибутов: {len(meta['metadata_map'])}, conf={meta['extraction_confidence']}")

        # Semantic Disambiguator (работает на Universal Repr)
        if verbose:
            print("\n  [3b] Semantic Disambiguator...")
        text_for_disambiguation = _build_text_for_disambiguation(universal)
        disamb = semantic_disambiguator.run(text_for_disambiguation)
        self.history.append({"role": "semantic_disambiguator", "output": disamb})
        if verbose:
            print(f"    Разрешено: {len(disamb['resolutions'])}, gap: {len(disamb['semantic_gaps'])}")

        # Context Resolver (с доменным контекстом)
        if verbose:
            print("\n  [3c] Context Resolver...")
        domain = domain_info.get("primary_domain")
        ctx = context_resolver.run(disamb.get("semantic_gaps", []), domain=domain if domain else None, context=text_for_disambiguation)
        self.history.append({"role": "context_resolver", "output": ctx})
        if verbose:
            print(f"    Разрешено: {len(ctx['resolved'])}, external: {len(ctx['external_gaps'])}")

        # Style Validator
        if verbose:
            print("\n  [3d] Style Validator...")
        style = style_validator.run([])
        self.history.append({"role": "style_validator", "output": style})
        if verbose:
            print(f"    Compliance: {style['compliance_score']}")

        # Graph Builder (работает на Universal Repr)
        if verbose:
            print("\n  [3e] Graph Builder...")
        graph = graph_builder.run(
            primitives=_extract_primitives_for_graph(universal),
            resolutions=disamb.get("resolutions", []) + ctx.get("resolved", []),
            violations=style.get("violations", []),
            spatial_cache={},
        )
        self.history.append({"role": "graph_builder", "output": graph})
        if verbose:
            nodes = len(graph['graph_structure'].get('nodes', []))
            edges = len(graph['graph_structure'].get('edges', []))
            print(f"    Узлов: {nodes}, связей: {edges}, conf={graph['overall_confidence']}")

        # Dispatcher — решение
        if verbose:
            print("\n  [3f] Dispatcher...")
        # Определяем doc_class из типов страниц
        page_types = universal["stats"]["page_types"]
        doc_class = "text_only"
        if page_types.get("mixed", 0) > 0:
            doc_class = "mixed_text_image"
        elif page_types.get("image-only", 0) > 0 and page_types.get("text-only", 0) > 0:
            doc_class = "mixed_text_image"

        metrics = {
            "current_confidence": graph.get("overall_confidence", 0.0),
            "gap_count": len(disamb.get("semantic_gaps", [])),
            "external_gap_count": len(ctx.get("external_gaps", [])),
            "elapsed_ms": int(self._elapsed() * 1000),
            "doc_class": doc_class,
        }
        dispatch = run(metrics)
        self.history.append({"role": "dispatcher", "output": dispatch})
        if verbose:
            print(f"    Решение: {dispatch['action']}")
            print(f"    Причина: {dispatch['reason'][:200]}")

        if verbose:
            print(f"\n{'=' * 60}")
            print(f"ИТОГ: {self._elapsed():.1f}s, action={dispatch['action']}")
            print(f"{'=' * 60}")

        return {
            "universal": universal,
            "domain": domain_info,
            "metadata": meta,
            "disambiguator": disamb,
            "context_resolver": ctx,
            "style": style,
            "graph": graph,
            "dispatch": dispatch,
            "history": self.history,
            "elapsed_s": round(self._elapsed(), 1),
        }


class EventBusPipeline(Pipeline):
    """Параллельный пайплайн: 3 стадии с параллельными ролями в Стадии 3.

    Стадия 1: Нормализация (L0)
    Стадия 2: Доменная принадлежность (SMD)
    Стадия 3: Анализ (parallel: Metadata + Disambiguator || Style Validator →
            Context Resolver → Graph Builder → Dispatcher)
    """

    def run(self, verbose: bool = True) -> dict:
        from src.orchestrator.roles import (
            context_resolver,
            graph_builder,
            metadata_extractor,
            semantic_disambiguator,
            style_validator,
        )

        if verbose:
            print("=" * 60)
            print("MAS EVENT-BUS PIPELINE: 3 стадии (Нормализация → Домен → Анализ)")
            print("=" * 60)

        # ═══════════════════════════════════════════════════════════
        # Стадия 1: Нормализация (L0) → Universal Representation
        # ═══════════════════════════════════════════════════════════
        if verbose:
            print("\n── Стадия 1: Нормализация ──")
        universal = normalize(self.pdf_path)
        self.history.append({"role": "normalizer", "output": universal})
        if verbose:
            stats = universal["stats"]
            print(f"  Страниц: {stats['total_pages']}, типы: {stats['page_types']}")

        # ═══════════════════════════════════════════════════════════
        # Стадия 2: Доменная принадлежность (SMD)
        # ═══════════════════════════════════════════════════════════
        if verbose:
            print("\n── Стадия 2: Доменная принадлежность (SMD) ──")
        domain_info = detect_domain(universal)
        self.history.append({"role": "domain_analyzer", "output": domain_info})
        if verbose:
            print(f"  Домены: {', '.join(d['domain'] for d in domain_info.get('domains', []))}")
            print(f"  Основной: {domain_info['primary_domain']}")
            print(f"  Glossaries: {', '.join(domain_info['glossaries_to_use'])}")

        # ═══════════════════════════════════════════════════════════
        # Стадия 3: Анализ + Преобразование (параллельный)
        # ═══════════════════════════════════════════════════════════
        if verbose:
            print("\n── Стадия 3: Анализ + Преобразование ──")

        # Stage 3a: Metadata Extractor || Semantic Disambiguator (parallel)
        if verbose:
            print("\n  [Stage 3a] Metadata || Disambiguator...")
        t0 = time.time()

        text_for_disambiguation = _build_text_for_disambiguation(universal)

        with ThreadPoolExecutor(max_workers=2) as pool:
            meta_future = pool.submit(metadata_extractor.run, self.pdf_path)
            disamb_future = pool.submit(semantic_disambiguator.run, text_for_disambiguation)
            meta = meta_future.result()
            disamb = disamb_future.result()

        stage3a_time = time.time() - t0
        self.history.append({"role": "metadata_extractor", "output": meta})
        self.history.append({"role": "semantic_disambiguator", "output": disamb})
        if verbose:
            print(f"    Metadata: {len(meta['metadata_map'])} атрибутов, conf={meta['extraction_confidence']}")
            print(f"    Disambiguator: {len(disamb['resolutions'])} resolved, {len(disamb['semantic_gaps'])} gaps")
            print(f"    ⏱ Stage 3a: {stage3a_time:.1f}s")

        # Stage 3b: Context Resolver → Graph Builder (sequential)
        if verbose:
            print("\n  [Stage 3b] Context Resolver → Graph Builder...")
        t0 = time.time()

        domain = domain_info.get("primary_domain")
        ctx = context_resolver.run(disamb.get("semantic_gaps", []), domain=domain if domain else None, context=text_for_disambiguation)
        self.history.append({"role": "context_resolver", "output": ctx})

        style = style_validator.run([])
        self.history.append({"role": "style_validator", "output": style})

        graph = graph_builder.run(
            primitives=_extract_primitives_for_graph(universal),
            resolutions=disamb.get("resolutions", []) + ctx.get("resolved", []),
            violations=style.get("violations", []),
            spatial_cache={},
        )
        self.history.append({"role": "graph_builder", "output": graph})

        stage3b_time = time.time() - t0
        if verbose:
            print(f"    Context: {len(ctx['resolved'])} resolved, {len(ctx['external_gaps'])} external")
            print(f"    Graph: conf={graph['overall_confidence']}")
            print(f"    ⏱ Stage 3b: {stage3b_time:.1f}s")

        # Stage 3c: Dispatcher
        if verbose:
            print("\n  [Stage 3c] Dispatcher...")

        page_types = universal["stats"]["page_types"]
        doc_class = "text_only"
        if page_types.get("mixed", 0) > 0:
            doc_class = "mixed_text_image"
        elif page_types.get("image-only", 0) > 0 and page_types.get("text-only", 0) > 0:
            doc_class = "mixed_text_image"

        metrics = {
            "current_confidence": graph.get("overall_confidence", 0.0),
            "gap_count": len(disamb.get("semantic_gaps", [])),
            "external_gap_count": len(ctx.get("external_gaps", [])),
            "elapsed_ms": int(self._elapsed() * 1000),
            "doc_class": doc_class,
        }
        dispatch = run(metrics)
        self.history.append({"role": "dispatcher", "output": dispatch})

        if verbose:
            print(f"    Решение: {dispatch['action']}")
            print(f"    Причина: {dispatch['reason'][:200]}")
            print(f"\n{'=' * 60}")
            print(f"ИТОГ: {self._elapsed():.1f}s, action={dispatch['action']}")
            print(f"Stage 3a: {stage3a_time:.1f}s | Stage 3b: {stage3b_time:.1f}s")
            print(f"{'=' * 60}")

        return {
            "universal": universal,
            "domain": domain_info,
            "metadata": meta,
            "disambiguator": disamb,
            "context_resolver": ctx,
            "style": style,
            "graph": graph,
            "dispatch": dispatch,
            "history": self.history,
            "elapsed_s": round(self._elapsed(), 1),
            "stage_times": {
                "stage3a_parallel": round(stage3a_time, 1),
                "stage3b_sequential": round(stage3b_time, 1),
            },
        }