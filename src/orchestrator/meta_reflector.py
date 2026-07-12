"""Meta-Reflector: Level 3 reflection for adaptive strategy in MAS Orchestrator."""

import re
from collections import Counter


class ConvergenceDetector:
    """Анализирует траекторию confidence и выявляет стагнацию."""

    def __init__(self, plateau_window: int = 3):
        self.plateau_window = plateau_window

    def analyze(self, history: list[dict]) -> dict:
        """
        Анализирует историю циклов на предмет стагнации.

        Returns:
            {"is_plateau": bool, "confidence_trajectory": list[float],
             "dominant_gap_type": str | None, "reason": str}
        """
        # Извлекаем confidence из истории
        confidences = []
        reflector_outputs = []

        for item in history:
            if item.get("role") == "reflector":
                reflection = item.get("content", "")
                conf_match = re.search(r"confidence[:\s]*(\d+\.?\d*)", reflection.lower())
                if conf_match:
                    confidences.append(float(conf_match.group(1)))
                else:
                    nums = re.findall(r"(\d+\.\d+)", reflection)
                    if nums:
                        confidences.append(float(nums[0]))

                # Извлекаем тип пробелов
                gap_patterns = ["syntax", "semantic", "structure", "implementation"]
                for pattern in gap_patterns:
                    if pattern.lower() in reflection.lower():
                        reflector_outputs.append(f"gap_{pattern}")
                        break
                else:
                    reflector_outputs.append("gap_unknown")

        # Если недостаточно данных - стагнации нет
        if len(confidences) < 2:
            return {
                "is_plateau": False,
                "confidence_trajectory": confidences,
                "dominant_gap_type": None,
                "reason": "Недостаточно данных",
            }

        # Проверяем на стагнацию (delta < 0.02)
        deltas = [confidences[i] - confidences[i - 1] for i in range(1, len(confidences))]
        is_plateau = all(abs(d) < 0.02 for d in deltas[-self.plateau_window :])

        # Определяем доминирующий тип пробела
        gap_counts = Counter(reflector_outputs)
        dominant_gap = gap_counts.most_common(1)[0][0] if gap_counts else None

        reason = ""
        if is_plateau:
            reason = f"Confidence стагнирует на {confidences[-1]:.2f} в течение {self.plateau_window} итераций"
        elif len(deltas) >= 3 and deltas[-1] < 0:
            reason = "Последняя итерация не улучшила confidence"

        return {
            "is_plateau": is_plateau,
            "confidence_trajectory": confidences,
            "dominant_gap_type": dominant_gap,
            "reason": reason,
        }


class StrategyAdaptor:
    """Динамически адаптирует стратегию рефлексии."""

    def __init__(self):
        self.strategy_registry = {
            "syntax_fix": {
                "reflector_prompt": "Фокус на синтаксис и точность формулировок",
                "focus_prompt_template": "Исправь синтаксические ошибки: {reflection}",
                "temperature": 0.1,
            },
            "semantic_align": {
                "reflector_prompt": "Проверь семантическую согласованность",
                "focus_prompt_template": "Уточни семантические связи: {reflection}",
                "temperature": 0.2,
            },
            "structure_verification": {
                "reflector_prompt": "Проверь структурную целостность",
                "focus_prompt_template": "Уточни структуру результатов: {reflection}",
                "temperature": 0.15,
            },
        }
        self.current_strategy = "syntax_fix"

    def update(self, convergence_result: dict) -> None:
        """Обновляет стратегию на основе анализа сходимости."""
        if convergence_result["is_plateau"]:
            # Сменить стратегию при стагнации
            if convergence_result.get("dominant_gap_type") == "gap_syntax":
                self.current_strategy = "semantic_align"
            elif convergence_result.get("dominant_gap_type") == "gap_semantic":
                self.current_strategy = "structure_verification"

    def get_reflector_prompt(self, base_prompt: str) -> str:
        """Возвращает адаптированный промпт для рефлектора."""
        strategy = self.strategy_registry[self.current_strategy]
        return f"{base_prompt}\n\nПРИОРИТЕТНО: {strategy['reflector_prompt']}"

    def get_focus_prompt(self, base_template: str, reflection: str) -> str:
        """Возвращает адаптированный уточняющий промпт для агента."""
        strategy = self.strategy_registry[self.current_strategy]
        return strategy["focus_prompt_template"].format(reflection=reflection)


class TerminationEngine:
    """Управляет условиями завершения циклов."""

    def should_terminate(self, confidence: float, convergence_result: dict, max_iterations: int) -> tuple[bool, str]:
        """
        Решает, нужно ли прекратить итерации.

        Returns:
            (should_stop: bool, reason: str)
        """
        if confidence >= 0.85:
            return True, "confidence достиг порога (>= 0.85)"

        if convergence_result["is_plateau"]:
            return True, "Достигнут максимум возможностей текущей стратегии"

        if len(convergence_result.get("confidence_trajectory", [])) >= max_iterations:
            return True, "Достигнут предел итераций"

        return False, ""


class MetaReflector:
    """Level 3 reflection: управляет процессом рефлексии для адаптивного улучшения."""

    def __init__(self):
        self.convergence_detector = ConvergenceDetector()
        self.strategy_adaptor = StrategyAdaptor()
        self.termination_engine = TerminationEngine()

    def analyze_and_adapt(self, history: list[dict], base_reflector_prompt: str) -> tuple[str | None, str | None]:
        """
        Анализирует историю и предлагает адаптацию стратегии.

        Returns:
            (new_reflector_prompt, focus_prompt_override) or (None, None)
        """
        convergence_result = self.convergence_detector.analyze(history)

        if not convergence_result["is_plateau"]:
            return None, None

        # Обновить стратегию
        self.strategy_adaptor.update(convergence_result)

        new_reflector_prompt = self.strategy_adaptor.get_reflector_prompt(base_reflector_prompt)

        # Формулировка объяснения адаптации для отладки
        reason = convergence_result.get("reason", "Адаптация стратегии")

        return new_reflector_prompt, reason


def meta_reflect_cycle(
    history: list[dict], base_reflector_prompt: str, max_iterations: int = 3
) -> tuple[bool, str, str | None]:
    """
    Попыткаmeta-рефлексии: анализ и адаптация стратегии.

    Returns:
        (success: bool, reason: str, new_prompt: Optional[str])
    """
    if len(history) < 2:
        return False, "Недостаточно данных для meta-reflection", None

    meta = MetaReflector()
    convergence_result = meta.convergence_detector.analyze(history)

    if not convergence_result["is_plateau"]:
        return True, "Confidence растет - адаптация не нужна", None

    new_prompt, reason = meta.analyze_and_adapt(history, base_reflector_prompt)

    if new_prompt:
        return True, f"Адаптация: {reason}", new_prompt

    # Остановить из-за стагнации
    success, termination_reason = meta.termination_engine.should_terminate(
        history[-1].get("confidence", 0.0), convergence_result, max_iterations
    )

    if success:
        return True, f"Стоп: {termination_reason}", None

    return False, "Продолжаем с текущей стратегией", None
