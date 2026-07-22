"""Шаг 3: Meta-Cognitive Doubt Gate — вентиль уверенности и триггер сомнений.

Блокирует выдачу C-level рекомендаций при confidence < порога.
Формирует «карту зон неизвестности».
Генерирует стратегические дилеммы (A vs B с равными рисками).
Инициирует обратный проход по графу для пересмотра.

Использует локальную Ollama (qwen3.6:35b).

Динамический порог confidence по классу документа (smd-map.yaml):
- text_only: 0.75 (простые текстовые документы)
- mixed_text_vector: 0.80 (текст + векторная графика)
- mixed_text_image: 0.82 (текст + растровые изображения)
- complex_diagram: 0.88 (сложные диаграммы: Venn, графики)
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field

from src.utils.config import OLLAMA_LOCAL_BASE
from src.utils.prompt_loader import load_prompt

MODEL = "qwen3.6:35b"
CONFIDENCE_THRESHOLD = 0.65  # Дефолтный порог (для обратной совместимости)

# Динамические пороги по классу документа (smd-map.yaml)
# Только классы по модальности (L0), без алиасов для знаковых форм СМД (L1)
DYNAMIC_THRESHOLDS = {
    "text_only": 0.75,              # Только текстовые примитивы
    "mixed_text_vector": 0.80,      # Текст + векторная графика
    "mixed_text_image": 0.82,       # Текст + растровые изображения
    "complex_diagram": 0.88,        # Сложные диаграммы (Venn, графики)
}


def dynamic_threshold(doc_class: str) -> float:
    """Возвращает динамический порог confidence для класса документа.
    
    Args:
        doc_class: класс документа (text_only, mixed_text_vector, mixed_text_image, complex_diagram)
                   или знаковая форма (discursive, topology, matrix, hierarchy, venn, spatial)
    
    Returns:
        Порог confidence (0.0-1.0)
    """
    return DYNAMIC_THRESHOLDS.get(doc_class, CONFIDENCE_THRESHOLD)


@dataclass
class DoubtAssessment:
    """Оценка сомнения."""
    page_id: int
    confidence: float
    threshold: float
    blocked: bool  # True = рекомендация заблокирована
    doc_class: str = "text_only"  # Класс документа для динамического порога
    unknown_zones: list[str] = field(default_factory=list)
    critical_assumptions: list[str] = field(default_factory=list)
    strategic_dilemmas: list[dict] = field(default_factory=list)
    recommended_action: str = ""  # "revisit" | "escalate" | "accept_with_caveat" | "reject"


def _call_ollama(prompt: str, max_tokens: int = 1024) -> str:
    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())["message"]["content"]


def _parse_json(text: str) -> dict:
    try:
        j1, j2 = text.find("{"), text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass
    return {}


class MetaCognitiveReflector:
    """Мета-когнитивный рефлектор: оценивает уверенность и блокирует/пропускает рекомендации."""

    ASSESS_PROMPT = load_prompt("orchestrator/doubt_gate_assess")

    def __init__(self, threshold: float = CONFIDENCE_THRESHOLD):
        self.threshold = threshold
        self.assessments: dict[int, DoubtAssessment] = {}

    def assess(self, page_id: int, ontology: dict, reflection: dict, doc_class: str = "text_only") -> DoubtAssessment:
        """Оценивает одну рекомендацию.
        
        Args:
            page_id: номер страницы
            ontology: онтология страницы
            reflection: рекомендация/рефлексия страницы
            doc_class: класс документа для динамического порога (по умолчанию "text_only")
        """
        t0 = time.time()

        # Динамический порог по классу документа
        threshold = dynamic_threshold(doc_class)

        ont_str = json.dumps(ontology, ensure_ascii=False)[:2000]
        refl_str = json.dumps(reflection, ensure_ascii=False)[:1000]

        prompt = self.ASSESS_PROMPT.format(ontology=ont_str, recommendation=refl_str)
        result = _parse_json(_call_ollama(prompt, max_tokens=1024))

        confidence = result.get("confidence", 0.5)
        blocked = confidence < threshold

        assessment = DoubtAssessment(
            page_id=page_id,
            confidence=confidence,
            threshold=threshold,
            blocked=blocked,
            doc_class=doc_class,
            unknown_zones=result.get("unknown_zones", []),
            critical_assumptions=result.get("critical_assumptions", []),
            strategic_dilemmas=result.get("strategic_dilemmas", []),
            recommended_action=result.get("recommended_action", "revisit" if blocked else "accept"),
        )

        self.assessments[page_id] = assessment

        elapsed = time.time() - t0
        status = "🚫 BLOCKED" if blocked else "✅ PASSED"
        print(f"    DoubtGate p{page_id}: conf={confidence:.2f} threshold={threshold:.2f} [{doc_class}] {status} → {assessment.recommended_action} — {elapsed:.1f}s")

        return assessment

    def assess_all(self, ontologies: dict[int, dict], reflections: dict[int, dict]) -> dict[int, DoubtAssessment]:
        """Оценивает все страницы."""
        for pid in ontologies:
            if pid in reflections:
                self.assess(pid, ontologies[pid], reflections[pid])
        return self.assessments

    def get_blocked_pages(self) -> list[int]:
        """Возвращает страницы с заблокированными рекомендациями."""
        return [pid for pid, a in self.assessments.items() if a.blocked]

    def get_unknown_zones_map(self) -> dict:
        """Карта зон неизвестности по всему документу."""
        zones = {}
        for pid, a in self.assessments.items():
            if a.unknown_zones:
                zones[pid] = {
                    "unknown_zones": a.unknown_zones,
                    "critical_assumptions": a.critical_assumptions,
                    "confidence": a.confidence,
                }
        return zones

    def get_dilemmas(self) -> list[dict]:
        """Все стратегические дилеммы."""
        dilemmas = []
        for pid, a in self.assessments.items():
            for d in a.strategic_dilemmas:
                dilemmas.append({"page": pid, **d})
        return dilemmas

    def to_dict(self) -> dict:
        return {
            "threshold": self.threshold,
            "dynamic_thresholds": DYNAMIC_THRESHOLDS,
            "assessments": {
                str(pid): {
                    "confidence": a.confidence,
                    "threshold": a.threshold,
                    "doc_class": a.doc_class,
                    "blocked": a.blocked,
                    "unknown_zones": a.unknown_zones,
                    "critical_assumptions": a.critical_assumptions,
                    "strategic_dilemmas": a.strategic_dilemmas,
                    "recommended_action": a.recommended_action,
                }
                for pid, a in self.assessments.items()
            },
            "blocked_count": len(self.get_blocked_pages()),
            "total_count": len(self.assessments),
        }