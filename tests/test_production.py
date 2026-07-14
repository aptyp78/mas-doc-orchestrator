"""Тесты production-фич: Batch, Dream Agent, VL Normalizer, ConfidenceGuard.

Запуск: python3 -m pytest tests/test_production.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.compute_resource import ComputeResourceManager, ComputeBudget
from src.confidence_guard import ConfidenceGuard, GuardAlert
from src.page_batch import process_pages_batch, aggregate_pages_to_documents

TEST_PDFS = [
    str(Path(__file__).resolve().parent.parent / "data" / "docs" / "ЦОД+ПАК.pdf"),
    str(Path(__file__).resolve().parent.parent / "data" / "docs" / "карта.pdf"),
]


# ═══════════════════════════════════════════════════════════════
# #1: Compute Resource Manager
# ═══════════════════════════════════════════════════════════════

class TestComputeResourceManager:
    def test_discovers_cpu(self):
        mgr = ComputeResourceManager()
        assert "local_cpu" in mgr.resources
        assert mgr.resources["local_cpu"].max_concurrent >= 2

    def test_budget_for_stage(self):
        mgr = ComputeResourceManager()
        budget = mgr.budget_for_stage("normalization")
        assert isinstance(budget, ComputeBudget)
        assert budget.local_workers >= 1
        assert budget.retry_max >= 2

    def test_acquire_release(self):
        mgr = ComputeResourceManager()
        assert mgr.acquire("local_cpu")
        assert mgr.resources["local_cpu"].current_load == 1
        mgr.release("local_cpu")
        assert mgr.resources["local_cpu"].current_load == 0

    def test_summary(self):
        mgr = ComputeResourceManager()
        summary = mgr.summary()
        assert "local_cpu" in summary
        assert summary["local_cpu"]["healthy"]


# ═══════════════════════════════════════════════════════════════
# #1: Page Batch Pipeline
# ═══════════════════════════════════════════════════════════════

class TestPageBatch:
    def test_process_single_pdf(self):
        """Обработка одного PDF как batch страниц."""
        pdf = TEST_PDFS[0]
        if not os.path.exists(pdf):
            pytest.skip(f"PDF not found: {pdf}")

        results = process_pages_batch([pdf], max_workers=2)
        assert len(results) >= 1
        for r in results:
            assert "page_id" in r
            assert "page_type" in r
            assert "elements" in r

    def test_aggregate_results(self):
        """Агрегация страниц в документы."""
        page_results = [
            {"pdf_path": "a.pdf", "page_id": 1, "page_type": "text-only", "elements": [], "element_count": 5},
            {"pdf_path": "a.pdf", "page_id": 2, "page_type": "image-only", "elements": [], "element_count": 3},
            {"pdf_path": "b.pdf", "page_id": 1, "page_type": "text-only", "elements": [], "element_count": 7},
        ]
        docs = aggregate_pages_to_documents(page_results)
        assert len(docs) == 2
        assert docs["a.pdf"]["total_pages"] == 2
        assert docs["a.pdf"]["elements_total"] == 8
        assert docs["b.pdf"]["total_pages"] == 1


# ═══════════════════════════════════════════════════════════════
# #5: ConfidenceGuard
# ═══════════════════════════════════════════════════════════════

class TestConfidenceGuard:
    def test_no_alerts_on_normal_data(self):
        guard = ConfidenceGuard(window_size=10)
        for i in range(10):
            guard.record("graph_builder", 0.85 + (i % 3) * 0.05, quality=0.8)
        alerts = guard.check()
        assert len(alerts) == 0

    def test_stagnation_alert(self):
        guard = ConfidenceGuard(window_size=10)
        for _ in range(10):
            guard.record("graph_builder", 0.95, quality=0.8)
        alerts = guard.check()
        assert any(a.rule == "stagnation" for a in alerts)

    def test_divergence_alert(self):
        guard = ConfidenceGuard(window_size=10)
        for i in range(10):
            guard.record("graph_builder", 0.80 + i * 0.02, quality=0.90 - i * 0.03)
        alerts = guard.check()
        assert any(a.rule == "divergence" for a in alerts)

    def test_overfitting_alert(self):
        guard = ConfidenceGuard(window_size=10)
        for _ in range(5):
            guard.record("graph", 0.95, doc_type="text-only")
        for _ in range(5):
            guard.record("graph", 0.70, doc_type="image-only")
        alerts = guard.check()
        assert any(a.rule == "overfitting" for a in alerts)

    def test_summary(self):
        guard = ConfidenceGuard(window_size=10)
        for i in range(5):
            guard.record("graph", 0.90)
        s = guard.summary()
        assert s["records"] == 5
        assert s["mean_confidence"] > 0

    def test_alert_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            guard = ConfidenceGuard(window_size=5, alert_dir=tmpdir)
            for _ in range(10):
                guard.record("graph", 0.95)
            guard.check()
            files = list(Path(tmpdir).glob("guard_*.json"))
            assert len(files) == 1, f"Expected 1 alert file, got {len(files)}"


# ═══════════════════════════════════════════════════════════════
# #4: VL Normalizer
# ═══════════════════════════════════════════════════════════════

class TestVLNormalizer:
    def test_compare_normalizers(self):
        """Сравнение PyMuPDF vs VL на одном документе."""
        pdf = TEST_PDFS[0]
        if not os.path.exists(pdf):
            pytest.skip(f"PDF not found: {pdf}")

        from src.normalizer.vl_normalizer import compare_normalizers
        result = compare_normalizers(pdf)
        assert "pymupdf" in result
        assert "vl" in result
        assert "winner" in result
        assert result["pymupdf"]["pages"] >= 1
        assert result["vl"]["pages"] >= 1
        # PyMuPDF должен быть быстрее
        assert result["time_ratio"] >= 1.0, f"VL unexpectedly faster: {result['time_ratio']}x"
        print(f"\nComparison: {json.dumps(result, indent=2, ensure_ascii=False)}")


# ═══════════════════════════════════════════════════════════════
# Интеграционный тест: полный прогон
# ═══════════════════════════════════════════════════════════════

class TestIntegration:
    def test_full_pipeline_with_guard(self):
        """Полный прогон пайплайна + ConfidenceGuard."""
        pdf = TEST_PDFS[0]
        if not os.path.exists(pdf):
            pytest.skip(f"PDF not found: {pdf}")

        # Проверяем доступность Ollama
        import urllib.request
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags")
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pytest.skip("Ollama not available")

        from src.orchestrator.roles.dispatcher import EventBusPipeline

        guard = ConfidenceGuard(window_size=10)
        pipeline = EventBusPipeline(pdf)
        result = pipeline.run(verbose=False)

        graph_conf = result["graph"]["overall_confidence"]
        guard.record("graph_builder", graph_conf, doc_type="text-only")

        alerts = guard.check()
        summary = guard.summary()

        assert result["dispatch"]["action"] in ("ITERATE", "TERMINATE", "FALLBACK")
        assert summary["records"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])