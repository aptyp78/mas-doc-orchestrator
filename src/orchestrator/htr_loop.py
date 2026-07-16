"""Шаг 1: Hypothesis-Test-Revisit Loop (HTR-цикл).

Вместо однопроходного извлечения — итеративный цикл:
  S_state → H_gen (гипотезы) → V_test (проверка) → Revise (пересмотр) → S_state'

Агенты:
- HypothesisGenerator: генерирует альтернативные стратегические сценарии
- Verifier/Falsifier: проверяет сценарии на внутреннюю согласованность
- LoopController: управляет итерациями до стабильности

Использует локальную Ollama (qwen3.6:35b).
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"
MAX_ITERATIONS = 3
STABILITY_THRESHOLD = 0.85  # overlap между итерациями для остановки


@dataclass
class Hypothesis:
    """Стратегическая гипотеза."""
    id: str
    statement: str
    supporting_evidence: list[str] = field(default_factory=list)
    counter_arguments: list[str] = field(default_factory=list)
    confidence: float = 0.5
    risks: list[str] = field(default_factory=list)
    opportunities: list[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    """Результат проверки гипотезы."""
    hypothesis_id: str
    is_consistent: bool
    contradictions: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    logical_gaps: list[str] = field(default_factory=list)
    revised_confidence: float = 0.5
    verdict: str = ""  # "accept" | "revise" | "reject"


@dataclass
class HTRState:
    """Состояние HTR-цикла."""
    iteration: int
    hypotheses: list[Hypothesis] = field(default_factory=list)
    verifications: list[VerificationResult] = field(default_factory=list)
    stable: bool = False
    convergence_score: float = 0.0


def _call_ollama(prompt: str, max_tokens: int = 2048) -> str:
    """Вызов локальной Ollama."""
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
    """Безопасный парсинг JSON из ответа LLM."""
    try:
        j1, j2 = text.find("{"), text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass
    return {}


class HypothesisGenerator:
    """Генерирует альтернативные стратегические сценарии из онтологии."""

    PROMPT = """[РОЛЬ] Генератор стратегических гипотез
[ПРЕДМЕТ] Онтологическая модель страницы документа
[ЗАДАЧА] Сгенерируй 2-3 альтернативные стратегические гипотезы
[ПРАВИЛА]
1. Каждая гипотеза — возможный сценарий действий для российского C-level
2. Для каждой гипотезы укажи: statement, supporting_evidence (из онтологии), counter_arguments, risks, opportunities
3. confidence: 0.0-1.0 — насколько онтология поддерживает гипотезу
4. Гипотезы должны быть РАЗЛИЧНЫМИ (не вариации одного и того же)
[ОГРАНИЧЕНИЕ] Только на основе онтологии. Не выдумывай факты.

Формат: JSON
{{
  "hypotheses": [
    {{
      "id": "H1",
      "statement": "string",
      "supporting_evidence": ["string"],
      "counter_arguments": ["string"],
      "risks": ["string"],
      "opportunities": ["string"],
      "confidence": 0.0-1.0
    }}
  ]
}}

## ОНТОЛОГИЯ
{ontology}"""

    def generate(self, ontology: dict) -> list[Hypothesis]:
        """Генерирует гипотезы из онтологии."""
        ont_str = json.dumps(ontology, ensure_ascii=False)[:3000]
        prompt = self.PROMPT.format(ontology=ont_str)
        result = _parse_json(_call_ollama(prompt))
        hypotheses = []
        for h in result.get("hypotheses", []):
            hypotheses.append(Hypothesis(
                id=h.get("id", f"H{len(hypotheses)}"),
                statement=h.get("statement", ""),
                supporting_evidence=h.get("supporting_evidence", []),
                counter_arguments=h.get("counter_arguments", []),
                confidence=h.get("confidence", 0.5),
                risks=h.get("risks", []),
                opportunities=h.get("opportunities", []),
            ))
        return hypotheses


class Verifier:
    """Проверяет гипотезы на внутреннюю согласованность."""

    PROMPT = """[РОЛЬ] Верификатор стратегических гипотез
[ПРЕДМЕТ] Гипотеза + исходная онтология
[ЗАДАЧА] Проверь гипотезу на внутреннюю согласованность
[ПРАВИЛА]
1. Найди ПРОТИВОРЕЧИЯ между гипотезой и онтологией
2. Найди ПРОБЕЛЫ в доказательной базе (missing_evidence)
3. Найди ЛОГИЧЕСКИЕ РАЗРЫВЫ (logical_gaps)
4. Вынеси ВЕРДИКТ: accept (принять), revise (пересмотреть), reject (отклонить)
5. Пересчитай confidence (0.0-1.0)
[ОГРАНИЧЕНИЕ] Будь строгим. Сомневайся.

Формат: JSON
{{
  "is_consistent": true/false,
  "contradictions": ["string"],
  "missing_evidence": ["string"],
  "logical_gaps": ["string"],
  "revised_confidence": 0.0-1.0,
  "verdict": "accept|revise|reject"
}}

## ОНТОЛОГИЯ
{ontology}

## ГИПОТЕЗА
{hypothesis}"""

    def verify(self, hypothesis: Hypothesis, ontology: dict) -> VerificationResult:
        """Проверяет одну гипотезу."""
        ont_str = json.dumps(ontology, ensure_ascii=False)[:2000]
        hyp_str = json.dumps({
            "statement": hypothesis.statement,
            "supporting_evidence": hypothesis.supporting_evidence,
            "confidence": hypothesis.confidence,
        }, ensure_ascii=False)

        prompt = self.PROMPT.format(ontology=ont_str, hypothesis=hyp_str)
        result = _parse_json(_call_ollama(prompt, max_tokens=1024))

        return VerificationResult(
            hypothesis_id=hypothesis.id,
            is_consistent=result.get("is_consistent", False),
            contradictions=result.get("contradictions", []),
            missing_evidence=result.get("missing_evidence", []),
            logical_gaps=result.get("logical_gaps", []),
            revised_confidence=result.get("revised_confidence", 0.5),
            verdict=result.get("verdict", "revise"),
        )


class HTRLoop:
    """Контроллер HTR-цикла."""

    def __init__(self, max_iterations: int = MAX_ITERATIONS):
        self.generator = HypothesisGenerator()
        self.verifier = Verifier()
        self.max_iterations = max_iterations
        self.history: list[HTRState] = []

    def run(self, ontology: dict, page_id: int = 0) -> HTRState:
        """Запускает HTR-цикл для одной страницы."""
        state = HTRState(iteration=0)
        previous_hypotheses: list[str] = []

        for iteration in range(1, self.max_iterations + 1):
            state.iteration = iteration
            t0 = time.time()

            # Генерация гипотез
            if iteration == 1:
                hypotheses = self.generator.generate(ontology)
            else:
                # Пересмотр: добавляем контекст противоречий
                enriched_ontology = dict(ontology)
                enriched_ontology["_previous_contradictions"] = [
                    c for v in state.verifications for c in v.contradictions
                ]
                enriched_ontology["_previous_gaps"] = [
                    g for v in state.verifications for g in v.logical_gaps
                ]
                hypotheses = self.generator.generate(enriched_ontology)

            state.hypotheses = hypotheses

            # Верификация
            verifications = []
            for h in hypotheses:
                vr = self.verifier.verify(h, ontology)
                verifications.append(vr)
            state.verifications = verifications

            # Проверка сходимости
            current_statements = {h.statement for h in hypotheses}
            if previous_hypotheses:
                overlap = len(current_statements & set(previous_hypotheses)) / max(
                    len(current_statements), len(previous_hypotheses), 1
                )
                state.convergence_score = overlap
                if overlap >= STABILITY_THRESHOLD:
                    state.stable = True

            previous_hypotheses = list(current_statements)

            elapsed = time.time() - t0
            accepted = sum(1 for v in verifications if v.verdict == "accept")
            print(f"    HTR iter {iteration}: {len(hypotheses)} hypotheses, "
                  f"{accepted} accepted, stable={state.stable} — {elapsed:.1f}s")

            if state.stable:
                break

        self.history.append(state)
        return state

    def get_best_hypothesis(self, state: HTRState) -> Hypothesis | None:
        """Возвращает лучшую гипотезу (принятую + максимальный confidence)."""
        accepted = [
            (h, v) for h, v in zip(state.hypotheses, state.verifications)
            if v.verdict == "accept"
        ]
        if not accepted:
            return None
        return max(accepted, key=lambda x: x[1].revised_confidence)[0]

    def to_dict(self, state: HTRState) -> dict:
        """Сериализует состояние HTR-цикла."""
        return {
            "iteration": state.iteration,
            "stable": state.stable,
            "convergence_score": state.convergence_score,
            "hypotheses": [
                {
                    "id": h.id,
                    "statement": h.statement,
                    "confidence": h.confidence,
                    "verdict": v.verdict,
                    "revised_confidence": v.revised_confidence,
                    "contradictions": v.contradictions,
                    "logical_gaps": v.logical_gaps,
                }
                for h, v in zip(state.hypotheses, state.verifications)
            ],
        }