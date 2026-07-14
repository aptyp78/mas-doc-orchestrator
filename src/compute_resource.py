"""Compute Resource Manager: учёт и распределение вычислительных ресурсов.

Учитывает:
- Локальные ресурсы: CPU cores, GPU (через Ollama), RAM
- Облачные ресурсы: DashScope ModelStudio (rate limits, latency)
- Динамический расчёт max_workers для каждой стадии пайплайна
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.config import OLLAMA_LOCAL_BASE


@dataclass
class ResourceState:
    """Текущее состояние вычислительного ресурса."""
    name: str
    kind: str  # "local_gpu" | "local_cpu" | "cloud_api"
    max_concurrent: int
    current_load: int = 0
    avg_latency_ms: float = 0.0
    error_count: int = 0
    last_used: float = 0.0

    @property
    def available(self) -> int:
        return max(0, self.max_concurrent - self.current_load)

    @property
    def healthy(self) -> bool:
        return self.error_count < 5


@dataclass
class ComputeBudget:
    """Бюджет вычислительных ресурсов для стадии пайплайна."""
    stage: str
    local_workers: int
    cloud_workers: int
    jitter_ms: tuple[float, float]  # (min, max)
    retry_max: int
    backoff_base_s: float


class ComputeResourceManager:
    """Управляет вычислительными ресурсами пайплайна.

    Автоматически определяет:
    - Доступные CPU cores
    - Доступность Ollama (локальный GPU)
    - Доступность DashScope (облако)
    - Оптимальное распределение workers по стадиям
    """

    def __init__(self):
        self.resources: dict[str, ResourceState] = {}
        self._discover_resources()

    def _discover_resources(self) -> None:
        """Обнаруживает доступные вычислительные ресурсы."""
        # CPU
        cpu_count = os.cpu_count() or 4
        self.resources["local_cpu"] = ResourceState(
            name="local_cpu",
            kind="local_cpu",
            max_concurrent=max(1, cpu_count - 2),
        )

        # Ollama (локальный GPU)
        ollama_available = self._check_ollama()
        if ollama_available:
            self.resources["local_gpu"] = ResourceState(
                name="local_gpu",
                kind="local_gpu",
                max_concurrent=2,  # Ollama обрабатывает запросы последовательно
            )

        # DashScope (облако)
        self.resources["cloud_api"] = ResourceState(
            name="cloud_api",
            kind="cloud_api",
            max_concurrent=4,  # Rate limit DashScope
        )

    def _check_ollama(self) -> bool:
        """Проверяет доступность Ollama."""
        try:
            req = urllib.request.Request(f"{OLLAMA_LOCAL_BASE}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return len(data.get("models", [])) > 0
        except Exception:
            return False

    def acquire(self, resource_kind: str) -> bool:
        """Захватывает слот ресурса. Возвращает True если удалось."""
        if resource_kind not in self.resources:
            return False
        res = self.resources[resource_kind]
        if res.available > 0:
            res.current_load += 1
            res.last_used = time.time()
            return True
        return False

    def release(self, resource_kind: str, latency_ms: float = 0, error: bool = False) -> None:
        """Освобождает слот ресурса."""
        if resource_kind in self.resources:
            res = self.resources[resource_kind]
            res.current_load = max(0, res.current_load - 1)
            if latency_ms > 0:
                # Экспоненциальное скользящее среднее
                alpha = 0.3
                res.avg_latency_ms = alpha * latency_ms + (1 - alpha) * res.avg_latency_ms
            if error:
                res.error_count += 1

    def budget_for_stage(self, stage: str) -> ComputeBudget:
        """Рассчитывает бюджет для стадии пайплайна."""
        budgets = {
            "normalization": ComputeBudget(
                stage="normalization",
                local_workers=self.resources.get("local_cpu", ResourceState("cpu", "local_cpu", 2)).max_concurrent,
                cloud_workers=0,
                jitter_ms=(100, 300),
                retry_max=3,
                backoff_base_s=1.0,
            ),
            "domain_analysis": ComputeBudget(
                stage="domain_analysis",
                local_workers=1 if "local_gpu" in self.resources else 0,
                cloud_workers=self.resources.get("cloud_api", ResourceState("api", "cloud_api", 2)).max_concurrent,
                jitter_ms=(500, 1500),
                retry_max=4,
                backoff_base_s=2.0,
            ),
            "page_analysis": ComputeBudget(
                stage="page_analysis",
                local_workers=min(2, self.resources.get("local_gpu", ResourceState("gpu", "local_gpu", 1)).max_concurrent),
                cloud_workers=self.resources.get("cloud_api", ResourceState("api", "cloud_api", 2)).max_concurrent,
                jitter_ms=(200, 800),
                retry_max=4,
                backoff_base_s=1.5,
            ),
            "graph_build": ComputeBudget(
                stage="graph_build",
                local_workers=1 if "local_gpu" in self.resources else 0,
                cloud_workers=1,
                jitter_ms=(500, 1500),
                retry_max=3,
                backoff_base_s=2.0,
            ),
        }
        return budgets.get(stage, budgets["page_analysis"])

    def summary(self) -> dict:
        """Возвращает сводку о ресурсах."""
        return {
            name: {
                "kind": r.kind,
                "max_concurrent": r.max_concurrent,
                "available": r.available,
                "avg_latency_ms": round(r.avg_latency_ms, 1),
                "healthy": r.healthy,
            }
            for name, r in self.resources.items()
        }