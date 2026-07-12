"""ОРП 4: Iteration & SLA Dispatcher.

Координирует роли, управляет циклами и таймаутами.
"""

from __future__ import annotations

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

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
    """Принимает решение о следующем действии.

    Args:
        system_metrics: метрики системы (confidence, deviation_pct, elapsed_ms, gap_count)
        max_iterations: максимум итераций
        base_sla_seconds: базовый SLA в секундах
        doc_class: класс документа
        max_tokens: лимит токенов
        temperature: температура

    Returns:
        dict с action, updated_thresholds, routing_map, reason
    """
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

    # Пытаемся распарсить JSON
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


class Pipeline:
    """Координирует выполнение ролей в правильном порядке."""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.start_time = time.time()
        self.history: list[dict] = []

    def _elapsed(self) -> float:
        return time.time() - self.start_time

    def run(self, verbose: bool = True) -> dict:
        """Запускает полный пайплайн: все 7 ролей + диспетчер."""
        from src.orchestrator.roles import (
            context_resolver,
            graph_builder,
            metadata_extractor,
            semantic_disambiguator,
            style_validator,
            visual_extractor,
        )

        if verbose:
            print("=" * 60)
            print("MAS PIPELINE: 7 ролей + Dispatcher")
            print("=" * 60)

        # Шаг 1: Metadata
        if verbose:
            print("\n[1/6] Metadata Extractor...")
        meta = metadata_extractor.run(self.pdf_path)
        self.history.append({"role": "metadata_extractor", "output": meta})
        if verbose:
            print(
                f"  Атрибутов: {len(meta['metadata_map'])}, "
                f"пропущено: {len(meta['missing_fields'])}, "
                f"confidence: {meta['extraction_confidence']}"
            )

        # Шаг 2: Visual Extractor (можно параллельно с Metadata)
        if verbose:
            print("\n[2/6] Visual Extractor...")
        visual = visual_extractor.run(self.pdf_path, dpi=72)
        self.history.append({"role": "visual_extractor", "output": visual})
        if verbose:
            page_types = [p["page_type"] for p in visual["pages_analysis"]]
            print(f"  Страниц: {len(visual['pages_analysis'])}, типы: {page_types}")

        # Шаг 3: Semantic Disambiguator
        if verbose:
            print("\n[3/6] Semantic Disambiguator...")
        text_for_disambiguation = json.dumps(
            {
                "metadata": meta["metadata_map"],
                "pages": [p.get("raw_output", "")[:500] for p in visual["pages_analysis"]],
            },
            ensure_ascii=False,
        )
        disamb = semantic_disambiguator.run(text_for_disambiguation)
        self.history.append({"role": "semantic_disambiguator", "output": disamb})
        if verbose:
            print(f"  Разрешено: {len(disamb['resolutions'])}, gap: {len(disamb['semantic_gaps'])}")

        # Шаг 4: Context Resolver
        if verbose:
            print("\n[4/6] Context Resolver...")
        ctx = context_resolver.run(disamb.get("semantic_gaps", []))
        self.history.append({"role": "context_resolver", "output": ctx})
        if verbose:
            print(f"  Разрешено через глоссарий: {len(ctx['resolved'])}, external gaps: {len(ctx['external_gaps'])}")

        # Шаг 5: Style Validator
        if verbose:
            print("\n[5/6] Style Validator...")
        style = style_validator.run(visual.get("primitives", []))
        self.history.append({"role": "style_validator", "output": style})
        if verbose:
            print(f"  Compliance: {style['compliance_score']}")

        # Шаг 6: Graph Builder
        if verbose:
            print("\n[6/6] Graph Builder...")
        graph = graph_builder.run(
            primitives=visual.get("primitives", []),
            resolutions=disamb.get("resolutions", []) + ctx.get("resolved", []),
            violations=style.get("violations", []),
            spatial_cache=visual.get("spatial_cache", {}),
        )
        self.history.append({"role": "graph_builder", "output": graph})
        if verbose:
            print(
                f"  Узлов: {len(graph['graph_structure'].get('nodes', []))}, "
                f"связей: {len(graph['graph_structure'].get('edges', []))}, "
                f"confidence: {graph['overall_confidence']}"
            )

        # Шаг 7: Dispatcher — решение
        if verbose:
            print("\n[Dispatcher] Принятие решения...")
        metrics = {
            "current_confidence": graph.get("overall_confidence", 0.0),
            "gap_count": len(disamb.get("semantic_gaps", [])),
            "external_gap_count": len(ctx.get("external_gaps", [])),
            "elapsed_ms": int(self._elapsed() * 1000),
            "doc_class": "mixed_text_vector",
        }
        dispatch = run(metrics)
        self.history.append({"role": "dispatcher", "output": dispatch})
        if verbose:
            print(f"  Решение: {dispatch['action']}")
            print(f"  Причина: {dispatch['reason'][:200]}")

        if verbose:
            print(f"\n{'=' * 60}")
            print(f"ИТОГ: {self._elapsed():.1f}s, action={dispatch['action']}")
            print(f"{'=' * 60}")

        return {
            "metadata": meta,
            "visual": visual,
            "disambiguator": disamb,
            "context_resolver": ctx,
            "style": style,
            "graph": graph,
            "dispatch": dispatch,
            "history": self.history,
            "elapsed_s": round(self._elapsed(), 1),
        }


class EventBusPipeline(Pipeline):
    """Параллельный пайплайн: независимые роли запускаются одновременно.

    Граф зависимостей:
    Stage 1 (parallel):  Metadata Extractor  ||  Visual Extractor
    Stage 2 (parallel):  Semantic Disambiguator  ||  Style Validator
    Stage 3 (sequential): Context Resolver → Graph Builder
    Stage 4 (sequential): Dispatcher
    """

    def run(self, verbose: bool = True) -> dict:
        from src.orchestrator.roles import (
            context_resolver,
            graph_builder,
            metadata_extractor,
            semantic_disambiguator,
            style_validator,
            visual_extractor,
        )

        if verbose:
            print("=" * 60)
            print("MAS EVENT-BUS PIPELINE: параллельные роли")
            print("=" * 60)

        # ── Stage 1: Metadata || Visual (parallel) ──
        if verbose:
            print("\n[Stage 1] Metadata Extractor || Visual Extractor...")
        t0 = time.time()

        with ThreadPoolExecutor(max_workers=2) as pool:
            meta_future = pool.submit(metadata_extractor.run, self.pdf_path)
            visual_future = pool.submit(visual_extractor.run, self.pdf_path, 72)

            meta = meta_future.result()
            visual = visual_future.result()

        stage1_time = time.time() - t0
        self.history.append({"role": "metadata_extractor", "output": meta})
        self.history.append({"role": "visual_extractor", "output": visual})

        if verbose:
            print(f"  Metadata: {len(meta['metadata_map'])} атрибутов, conf={meta['extraction_confidence']}")
            page_types = [p["page_type"] for p in visual["pages_analysis"]]
            print(f"  Visual: {len(visual['pages_analysis'])} стр., типы: {page_types}")
            print(f"  ⏱ Stage 1: {stage1_time:.1f}s (вместо суммы sequential)")

        # ── Stage 2: Disambiguator || Validator (parallel) ──
        if verbose:
            print("\n[Stage 2] Semantic Disambiguator || Style Validator...")
        t0 = time.time()

        text_for_disambiguation = json.dumps(
            {
                "metadata": meta["metadata_map"],
                "pages": [p.get("raw_output", "")[:500] for p in visual["pages_analysis"]],
            },
            ensure_ascii=False,
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            disamb_future = pool.submit(semantic_disambiguator.run, text_for_disambiguation)
            style_future = pool.submit(style_validator.run, visual.get("primitives", []))

            disamb = disamb_future.result()
            style = style_future.result()

        stage2_time = time.time() - t0
        self.history.append({"role": "semantic_disambiguator", "output": disamb})
        self.history.append({"role": "style_validator", "output": style})

        if verbose:
            print(f"  Disambiguator: {len(disamb['resolutions'])} resolved, {len(disamb['semantic_gaps'])} gaps")
            print(f"  Validator: compliance={style['compliance_score']}")
            print(f"  ⏱ Stage 2: {stage2_time:.1f}s")

        # ── Stage 3: Context Resolver → Graph Builder (sequential) ──
        if verbose:
            print("\n[Stage 3] Context Resolver → Graph Builder...")
        t0 = time.time()

        ctx = context_resolver.run(disamb.get("semantic_gaps", []))
        self.history.append({"role": "context_resolver", "output": ctx})

        graph = graph_builder.run(
            primitives=visual.get("primitives", []),
            resolutions=disamb.get("resolutions", []) + ctx.get("resolved", []),
            violations=style.get("violations", []),
            spatial_cache=visual.get("spatial_cache", {}),
        )
        self.history.append({"role": "graph_builder", "output": graph})

        stage3_time = time.time() - t0
        if verbose:
            print(f"  Context: {len(ctx['resolved'])} resolved, {len(ctx['external_gaps'])} external")
            print(f"  Graph: conf={graph['overall_confidence']}")
            print(f"  ⏱ Stage 3: {stage3_time:.1f}s")

        # ── Stage 4: Dispatcher ──
        if verbose:
            print("\n[Stage 4] Dispatcher...")
        metrics = {
            "current_confidence": graph.get("overall_confidence", 0.0),
            "gap_count": len(disamb.get("semantic_gaps", [])),
            "external_gap_count": len(ctx.get("external_gaps", [])),
            "elapsed_ms": int(self._elapsed() * 1000),
            "doc_class": "mixed_text_vector",
        }
        dispatch = run(metrics)
        self.history.append({"role": "dispatcher", "output": dispatch})

        if verbose:
            print(f"  Решение: {dispatch['action']}")
            print(f"  Причина: {dispatch['reason'][:200]}")
            print(f"\n{'=' * 60}")
            print(f"ИТОГ: {self._elapsed():.1f}s (parallel), action={dispatch['action']}")
            print(f"Stage 1: {stage1_time:.1f}s | Stage 2: {stage2_time:.1f}s | Stage 3: {stage3_time:.1f}s")
            print(f"{'=' * 60}")

        return {
            "metadata": meta,
            "visual": visual,
            "disambiguator": disamb,
            "context_resolver": ctx,
            "style": style,
            "graph": graph,
            "dispatch": dispatch,
            "history": self.history,
            "elapsed_s": round(self._elapsed(), 1),
            "stage_times": {
                "stage1_parallel": round(stage1_time, 1),
                "stage2_parallel": round(stage2_time, 1),
                "stage3_sequential": round(stage3_time, 1),
            },
        }
