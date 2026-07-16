"""Шаг 6: SMD Orchestration Core — центральный контроллер режимов мышления.

FSM-контроллер, переключающий систему между фазами:
  Exploration → Synthesis → Doubt → Dialogue → Verification → (loop)

Управляет:
- Маршрутизацией между локальными моделями Ollama
- Сохранением контекста в sovereign memory
- Таймаутами инициации рефлексии
- Приоритизацией режимов (низкий confidence → Dialogue → Doubt)

Полностью автономен, не требует внешних вызовов.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from src.orchestrator.htr_loop import HTRLoop, HTRState
from src.orchestrator.cross_page_synthesizer import CrossPageSynthesizer
from src.orchestrator.doubt_gate import MetaCognitiveReflector, DoubtAssessment
from src.orchestrator.dialogue_mediator import DialogueOrchestrator, DialogueState
from src.orchestrator.provenance import ProvenanceMapper, ProvenanceChain


class OrchestrationMode(Enum):
    """Режимы оркестрации."""
    EXPLORATION = auto()   # Генерация гипотез (HTR-цикл)
    SYNTHESIS = auto()     # Кросс-страничный синтез
    DOUBT = auto()         # Оценка уверенности, блокировка
    DIALOGUE = auto()      # Многопозиционная аргументация
    VERIFICATION = auto()  # Проверка provenancе
    COMPLETE = auto()      # Завершено


@dataclass
class OrchestrationState:
    """Состояние оркестрации для одной страницы."""
    page_id: int
    mode: OrchestrationMode = OrchestrationMode.EXPLORATION

    # Данные пайплайна
    classification: dict = field(default_factory=dict)
    schema: dict = field(default_factory=dict)
    ontology: dict = field(default_factory=dict)
    reflection: dict = field(default_factory=dict)

    # Результаты оркестрации
    htr_state: HTRState | None = None
    doubt_assessment: DoubtAssessment | None = None
    dialogue_state: DialogueState | None = None
    provenance_chain: ProvenanceChain | None = None

    # Мета-данные
    iterations: int = 0
    elapsed_s: float = 0.0
    final_recommendation: dict = field(default_factory=dict)
    quality_score: float = 0.0

    @property
    def is_complete(self) -> bool:
        return self.mode == OrchestrationMode.COMPLETE


@dataclass
class OrchestrationResult:
    """Финальный результат оркестрации всего документа."""
    page_states: dict[int, OrchestrationState] = field(default_factory=dict)
    cross_page_graph: dict = field(default_factory=dict)
    macro_structure: dict = field(default_factory=dict)
    total_elapsed_s: float = 0.0
    summary: dict = field(default_factory=dict)


class SMDOrchestrationCore:
    """Центральное ядро SMD-оркестрации."""

    def __init__(self):
        self.htr_loop = HTRLoop(max_iterations=3)
        self.synthesizer = CrossPageSynthesizer()
        self.doubt_gate = MetaCognitiveReflector(threshold=0.65)
        self.dialogue = DialogueOrchestrator()
        self.provenance = ProvenanceMapper()

        self.mode_handlers = {
            OrchestrationMode.EXPLORATION: self._handle_exploration,
            OrchestrationMode.SYNTHESIS: self._handle_synthesis,
            OrchestrationMode.DOUBT: self._handle_doubt,
            OrchestrationMode.DIALOGUE: self._handle_dialogue,
            OrchestrationMode.VERIFICATION: self._handle_verification,
        }

    def _next_mode(self, current: OrchestrationMode, state: OrchestrationState) -> OrchestrationMode:
        """Определяет следующий режим на основе текущего состояния."""
        if current == OrchestrationMode.EXPLORATION:
            return OrchestrationMode.SYNTHESIS

        if current == OrchestrationMode.SYNTHESIS:
            return OrchestrationMode.DOUBT

        if current == OrchestrationMode.DOUBT:
            if state.doubt_assessment and state.doubt_assessment.blocked:
                return OrchestrationMode.DIALOGUE
            return OrchestrationMode.VERIFICATION

        if current == OrchestrationMode.DIALOGUE:
            return OrchestrationMode.VERIFICATION

        if current == OrchestrationMode.VERIFICATION:
            return OrchestrationMode.COMPLETE

        return OrchestrationMode.COMPLETE

    def _handle_exploration(self, state: OrchestrationState) -> OrchestrationState:
        """HTR-цикл: генерация и проверка гипотез."""
        if not state.ontology:
            state.mode = OrchestrationMode.COMPLETE
            return state

        print(f"  [EXPLORATION] p{state.page_id}: HTR-цикл...")
        t0 = time.time()

        state.htr_state = self.htr_loop.run(state.ontology, state.page_id)
        state.iterations = state.htr_state.iteration

        # Лучшая гипотеза
        best = self.htr_loop.get_best_hypothesis(state.htr_state)
        if best:
            state.final_recommendation = {
                "action": best.statement,
                "confidence": best.confidence,
                "risks": best.risks,
                "opportunities": best.opportunities,
                "evidence": best.supporting_evidence,
            }

        state.elapsed_s += time.time() - t0
        return state

    def _handle_synthesis(self, state: OrchestrationState) -> OrchestrationState:
        """Кросс-страничный синтез (отложенный — запускается после всех страниц)."""
        # Синтез делается один раз для всего документа, здесь только метка
        return state

    def _handle_doubt(self, state: OrchestrationState) -> OrchestrationState:
        """Мета-когнитивная оценка."""
        if not state.ontology or not state.reflection:
            state.mode = OrchestrationMode.COMPLETE
            return state

        print(f"  [DOUBT] p{state.page_id}: оценка уверенности...")
        t0 = time.time()

        state.doubt_assessment = self.doubt_gate.assess(
            state.page_id, state.ontology, state.reflection,
        )
        state.elapsed_s += time.time() - t0
        return state

    def _handle_dialogue(self, state: OrchestrationState) -> OrchestrationState:
        """Стратегический диалог."""
        if not state.ontology or not state.reflection:
            state.mode = OrchestrationMode.COMPLETE
            return state

        print(f"  [DIALOGUE] p{state.page_id}: многопозиционная аргументация...")
        t0 = time.time()

        state.dialogue_state = self.dialogue.start_dialogue(
            str(state.page_id), state.ontology, state.reflection,
        )
        state.elapsed_s += time.time() - t0
        return state

    def _handle_verification(self, state: OrchestrationState) -> OrchestrationState:
        """Provenance-верификация."""
        print(f"  [VERIFICATION] p{state.page_id}: provenancе-цепь...")
        t0 = time.time()

        state.provenance_chain = self.provenance.build_chain_from_pipeline(
            state.page_id,
            state.classification,
            state.schema,
            state.ontology,
            state.reflection,
        )

        # Оценка качества
        chain_valid = state.provenance_chain.is_valid
        doubt_ok = state.doubt_assessment and not state.doubt_assessment.blocked
        htr_stable = state.htr_state and state.htr_state.stable

        quality = 0.0
        if chain_valid:
            quality += 0.4
        if doubt_ok:
            quality += 0.3
        if htr_stable:
            quality += 0.3
        state.quality_score = quality

        state.elapsed_s += time.time() - t0
        return state

    def orchestrate_page(self, page_id: int, classification: dict, schema: dict,
                         ontology: dict, reflection: dict) -> OrchestrationState:
        """Оркестрирует одну страницу через все режимы."""
        state = OrchestrationState(
            page_id=page_id,
            classification=classification,
            schema=schema,
            ontology=ontology,
            reflection=reflection,
        )

        t_total = time.time()
        mode = OrchestrationMode.EXPLORATION
        max_iterations = 10  # защита от бесконечного цикла

        while mode != OrchestrationMode.COMPLETE and state.iterations < max_iterations:
            handler = self.mode_handlers.get(mode)
            if handler:
                state = handler(state)
            state.iterations += 1
            mode = self._next_mode(mode, state)

        state.elapsed_s = time.time() - t_total

        status = "✅" if state.quality_score >= 0.6 else "⚠️" if state.quality_score >= 0.3 else "❌"
        print(f"  p{page_id}: {status} quality={state.quality_score:.2f} "
              f"mode={state.mode.name} — {state.elapsed_s:.1f}s")

        return state

    def orchestrate_document(self, pipeline_data: dict) -> OrchestrationResult:
        """Оркестрирует весь документ."""
        t_total = time.time()
        result = OrchestrationResult()

        # Постраничная оркестрация
        for page_id in pipeline_data.get("pages", []):
            state = self.orchestrate_page(
                page_id=page_id,
                classification=pipeline_data.get("classification", {}).get(str(page_id), {}),
                schema=pipeline_data.get("schemas", {}).get(str(page_id), {}),
                ontology=pipeline_data.get("ontologies", {}).get(str(page_id), {}),
                reflection=pipeline_data.get("reflections", {}).get(str(page_id), {}),
            )
            result.page_states[page_id] = state

        # Кросс-страничный синтез
        print("\n  [SYNTHESIS] Кросс-страничный синтез...")
        ontologies = {
            pid: state.ontology
            for pid, state in result.page_states.items()
            if state.ontology
        }
        if ontologies:
            self.synthesizer.build_graph(ontologies)
            result.cross_page_graph = self.synthesizer.to_dict()
            result.macro_structure = self.synthesizer.synthesize_macro_structure(ontologies)

        result.total_elapsed_s = time.time() - t_total

        # Сводка
        completed = sum(1 for s in result.page_states.values() if s.is_complete)
        high_quality = sum(1 for s in result.page_states.values() if s.quality_score >= 0.6)
        blocked = sum(1 for s in result.page_states.values()
                      if s.doubt_assessment and s.doubt_assessment.blocked)

        result.summary = {
            "total_pages": len(result.page_states),
            "completed": completed,
            "high_quality": high_quality,
            "blocked_by_doubt": blocked,
            "total_elapsed_s": result.total_elapsed_s,
            "cross_page_edges": len(result.cross_page_graph.get("edges", [])),
            "macro_clusters": len(result.macro_structure.get("clusters", [])),
        }

        print(f"\n  Оркестрация завершена: {result.total_elapsed_s:.1f}s")
        print(f"  Страниц: {completed}/{len(result.page_states)} completed")
        print(f"  Качество: {high_quality} high, {blocked} blocked")

        return result

    def to_dict(self, result: OrchestrationResult) -> dict:
        """Полная сериализация результата."""
        return {
            "summary": result.summary,
            "pages": {
                str(pid): {
                    "mode": state.mode.name,
                    "quality_score": state.quality_score,
                    "final_recommendation": state.final_recommendation,
                    "doubt": {
                        "blocked": state.doubt_assessment.blocked if state.doubt_assessment else False,
                        "confidence": state.doubt_assessment.confidence if state.doubt_assessment else 0.0,
                        "unknown_zones": state.doubt_assessment.unknown_zones if state.doubt_assessment else [],
                    } if state.doubt_assessment else None,
                    "htr": self.htr_loop.to_dict(state.htr_state) if state.htr_state else None,
                    "dialogue": self.dialogue.to_dict() if state.dialogue_state else None,
                    "provenance": state.provenance_chain.to_dict() if state.provenance_chain else None,
                    "elapsed_s": state.elapsed_s,
                }
                for pid, state in result.page_states.items()
            },
            "cross_page": result.cross_page_graph,
            "macro_structure": result.macro_structure,
            "provenance": self.provenance.to_dict(),
        }