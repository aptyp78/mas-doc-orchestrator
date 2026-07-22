"""Ingestion module — подготовка входных материалов для pipeline."""

from .format_detector import FormatDetectorAgent, prepare_for_pipeline

__all__ = ["FormatDetectorAgent", "prepare_for_pipeline"]
