#!/usr/bin/env python3
"""Валидация production-фич: замер ключевых метрик ДО и ПОСЛЕ внедрения.

Запуск:
  python3 scripts/validate_production.py

Метрики:
  - Время обработки (batch vs sequential)
  - Коэффициент утилизации агентов
  - Стабильность confidence
  - Качество нормализации (PyMuPDF vs VL)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from statistics import mean, stdev

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.compute_resource import ComputeResourceManager
from src.confidence_guard import ConfidenceGuard
from src.page_batch import process_pages_batch, aggregate_pages_to_documents

TEST_DOCS = [
    "data/docs/ЦОД+ПАК.pdf",
    "data/docs/карта.pdf",
    "data/docs/20260709_ПСБ_2030_v7а.pdf",
]

# ═══════════════════════════════════════════════════════════════
# Метрики успешности
# ═══════════════════════════════════════════════════════════════

SUCCESS_CRITERIA = {
    "batch_efficiency": {
        "metric": "total_time / max(single_time)",
        "target": "≤ 2.0",
        "critical": True,
    },
    "agent_utilization": {
        "metric": "agent_busy_time / total_time",
        "target": "→ 1.0",
        "critical": False,
    },
    "confidence_stability": {
        "metric": "std(confidence) за N запусков",
        "target": "> 0.02 (не стагнирует)",
        "critical": True,
    },
    "confidence_divergence": {
        "metric": "correlation(confidence, quality)",
        "target": "≥ 0 (не отрицательная)",
        "critical": True,
    },
    "normalizer_text_coverage": {
        "metric": "text_chars_vl / text_chars_pymupdf",
        "target": "≥ 0.8 на image-only",
        "critical": False,
    },
}


def validate_batch() -> dict:
    """Проверяет эффективность batch-обработки."""
    print("\n── #1: Batch Efficiency ──")
    existing = [p for p in TEST_DOCS if os.path.exists(p)]
    if len(existing) < 2:
        return {"status": "SKIP", "reason": "need ≥2 documents"}

    mgr = ComputeResourceManager()
    budget = mgr.budget_for_stage("normalization")

    # Последовательная обработка
    t0 = time.time()
    for pdf in existing:
        from src.normalizer.pdf_normalizer import normalize
        normalize(pdf)
    sequential_s = time.time() - t0

    # Batch-обработка
    t0 = time.time()
    results = process_pages_batch(existing, max_workers=budget.local_workers)
    batch_s = time.time() - t0

    efficiency = batch_s / max(sequential_s, 0.1)
    passed = efficiency <= 2.0

    print(f"  Sequential: {sequential_s:.1f}s")
    print(f"  Batch:      {batch_s:.1f}s (workers={budget.local_workers})")
    print(f"  Efficiency: {efficiency:.1f}x (target ≤ 2.0) → {'✅' if passed else '❌'}")

    return {
        "sequential_s": round(sequential_s, 1),
        "batch_s": round(batch_s, 1),
        "efficiency": round(efficiency, 1),
        "passed": passed,
    }


def validate_confidence_guard() -> dict:
    """Проверяет ConfidenceGuard."""
    print("\n── #5: ConfidenceGuard ──")

    guard = ConfidenceGuard(window_size=20)

    # Нормальные данные
    for i in range(15):
        guard.record("graph", 0.85 + (i % 5) * 0.03, quality=0.80 + (i % 3) * 0.02)
    alerts_normal = guard.check()

    # Стагнация
    guard2 = ConfidenceGuard(window_size=20)
    for _ in range(15):
        guard2.record("graph", 0.95, quality=0.80)
    alerts_stagnation = guard2.check()

    # Divergence
    guard3 = ConfidenceGuard(window_size=20)
    for i in range(15):
        guard3.record("graph", 0.80 + i * 0.015, quality=0.90 - i * 0.02)
    alerts_divergence = guard3.check()

    stagnation_detected = any(a.rule == "stagnation" for a in alerts_stagnation)
    divergence_detected = any(a.rule == "divergence" for a in alerts_divergence)
    no_false_positives = len(alerts_normal) == 0

    passed = stagnation_detected and divergence_detected and no_false_positives

    print(f"  Normal:        {len(alerts_normal)} alerts → {'✅' if no_false_positives else '❌'}")
    print(f"  Stagnation:    detected={'✅' if stagnation_detected else '❌'}")
    print(f"  Divergence:    detected={'✅' if divergence_detected else '❌'}")
    print(f"  Overall:       {'✅' if passed else '❌'}")

    return {
        "false_positives": len(alerts_normal),
        "stagnation_detected": stagnation_detected,
        "divergence_detected": divergence_detected,
        "passed": passed,
    }


def validate_normalizers() -> dict:
    """Сравнивает PyMuPDF и VL нормализаторы."""
    print("\n── #4: Normalizer Comparison ──")
    existing = [p for p in TEST_DOCS if os.path.exists(p)]
    if not existing:
        return {"status": "SKIP", "reason": "no documents"}

    from src.normalizer.vl_normalizer import compare_normalizers

    results = []
    for pdf in existing:
        cmp = compare_normalizers(pdf)
        results.append(cmp)
        ratio = cmp["pymupdf"]["text_chars"] / max(cmp["vl"]["text_chars"], 1)
        print(f"  {os.path.basename(pdf)}: PyMuPDF={cmp['pymupdf']['time_s']}s, VL={cmp['vl']['time_s']}s, text_ratio={ratio:.1f}x")

    passed = all(r["time_ratio"] >= 1.0 for r in results)  # PyMuPDF быстрее
    print(f"  Overall: {'✅' if passed else '❌'} (PyMuPDF faster on all docs)")

    return {"results": results, "passed": passed}


def main():
    print("=" * 55)
    print("ВАЛИДАЦИЯ PRODUCTION-ФИЧ")
    print("=" * 55)

    results = {}

    results["batch"] = validate_batch()
    results["confidence_guard"] = validate_confidence_guard()
    results["normalizers"] = validate_normalizers()

    # Сводка
    print("\n" + "=" * 55)
    print("СВОДКА")
    print("=" * 55)
    passed = sum(1 for r in results.values() if r.get("passed", False))
    total = sum(1 for r in results.values() if r.get("status") != "SKIP")
    print(f"  Пройдено: {passed}/{total}")

    for name, result in results.items():
        status = "✅" if result.get("passed") else ("⏭" if result.get("status") == "SKIP" else "❌")
        print(f"  {status} {name}")

    # Сохраняем
    out_path = "output/validation.json"
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nСохранено: {out_path}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())