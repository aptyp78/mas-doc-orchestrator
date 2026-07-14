"""ConfidenceGuard: защита confidence-метрики от reward hacking.

Мониторит confidence-оценки агентов и детектирует:
1. Стагнацию: std(confidence) < 0.02 — признак взлома метрики
2. Divergence: confidence растёт, а quality падает
3. Overfitting: резкое падение confidence при смене типа документа
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, stdev


@dataclass
class ConfidenceRecord:
    """Запись о confidence-оценке."""
    timestamp: float
    source: str  # "disambiguator", "graph_builder", "reflector"
    confidence: float
    quality: float | None = None  # из Reflector (если есть)
    doc_type: str = ""


@dataclass
class GuardAlert:
    """Предупреждение ConfidenceGuard."""
    level: str  # "WARNING" | "CRITICAL"
    rule: str
    detail: str
    timestamp: float = field(default_factory=time.time)


class ConfidenceGuard:
    """Мониторинг confidence-метрик.

    Usage:
        guard = ConfidenceGuard(window_size=20)
        guard.record("graph_builder", 0.95, quality=0.7)
        alerts = guard.check()
    """

    def __init__(self, window_size: int = 20, alert_dir: str | None = None):
        self.window_size = window_size
        self.history: deque[ConfidenceRecord] = deque(maxlen=window_size)
        self.alerts: list[GuardAlert] = []
        self.alert_dir = Path(alert_dir) if alert_dir else None

    def record(
        self,
        source: str,
        confidence: float,
        quality: float | None = None,
        doc_type: str = "",
    ) -> None:
        """Записывает confidence-оценку."""
        self.history.append(ConfidenceRecord(
            timestamp=time.time(),
            source=source,
            confidence=confidence,
            quality=quality,
            doc_type=doc_type,
        ))

    def check(self) -> list[GuardAlert]:
        """Проверяет историю на аномалии."""
        new_alerts: list[GuardAlert] = []

        if len(self.history) < 5:
            return new_alerts

        confidences = [r.confidence for r in self.history]
        qualities = [r.quality for r in self.history if r.quality is not None]

        # 1. Стагнация: все confidence одинаковые
        if len(confidences) >= 10:
            std = stdev(confidences) if len(confidences) > 1 else 0
            if std < 0.02:
                new_alerts.append(GuardAlert(
                    level="WARNING",
                    rule="stagnation",
                    detail=f"std(confidence)={std:.4f} < 0.02 за {len(confidences)} запусков — возможен взлом метрики",
                ))

        # 2. Divergence: confidence растёт, quality падает
        if len(qualities) >= 5:
            conf_trend = confidences[-1] - confidences[0]
            qual_trend = qualities[-1] - qualities[0] if qualities else 0
            if conf_trend > 0.05 and qual_trend < -0.05:
                new_alerts.append(GuardAlert(
                    level="CRITICAL",
                    rule="divergence",
                    detail=f"confidence +{conf_trend:.2f}, quality {qual_trend:.2f} — divergence",
                ))

        # 3. Overfitting: резкое падение при смене doc_type
        doc_types = [r.doc_type for r in self.history if r.doc_type]
        if len(set(doc_types)) >= 2:
            by_type: dict[str, list[float]] = {}
            for r in self.history:
                if r.doc_type:
                    by_type.setdefault(r.doc_type, []).append(r.confidence)
            if len(by_type) >= 2:
                means = {t: mean(cs) for t, cs in by_type.items()}
                max_mean = max(means.values())
                min_mean = min(means.values())
                if max_mean - min_mean > 0.15:
                    new_alerts.append(GuardAlert(
                        level="WARNING",
                        rule="overfitting",
                        detail=f"confidence gap {max_mean - min_mean:.2f} между типами: {means}",
                    ))

        self.alerts.extend(new_alerts)
        self._save_alerts(new_alerts)
        return new_alerts

    def _save_alerts(self, alerts: list[GuardAlert]) -> None:
        """Сохраняет алерты в файл."""
        if not self.alert_dir or not alerts:
            return
        self.alert_dir.mkdir(parents=True, exist_ok=True)
        fpath = self.alert_dir / f"guard_{int(time.time())}.json"
        with open(fpath, "w") as f:
            json.dump(
                [{"level": a.level, "rule": a.rule, "detail": a.detail} for a in alerts],
                f, ensure_ascii=False, indent=2,
            )

    def summary(self) -> dict:
        """Возвращает сводку о состоянии метрик."""
        if not self.history:
            return {"records": 0, "alerts": len(self.alerts)}
        confs = [r.confidence for r in self.history]
        return {
            "records": len(confs),
            "alerts": len(self.alerts),
            "mean_confidence": round(mean(confs), 3),
            "std_confidence": round(stdev(confs), 4) if len(confs) > 1 else 0,
        }