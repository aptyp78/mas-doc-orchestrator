"""Ядро оркестратора: Agent → Reflector → Agent → ... циклы с confidence-gated эскалацией."""

import json
import re
import time

from src.agents.dashscope import dashscope_chat, dashscope_vision
from src.utils.config import AGENT_VISION_MODEL, CONFIDENCE_THRESHOLD, MAX_REFLECTION_ITERATIONS, REFLECTOR_MODEL

AGENT_PROMPT = """Ты — агент структурного анализа диаграмм. Проанализируй изображение как граф знаний.

1. ОПИШИ ВСЕ БЛОКИ: для каждого — ID, текст, приблизительное положение (верх/низ/лево/право/центр)
2. ОПИШИ ВСЕ СВЯЗИ: стрелки, линии, группировки — откуда→куда, тип
3. ОПИШИ ИЕРАРХИЮ: какие блоки вложены в другие, какие сгруппированы
4. ОЦЕНИ СВОЮ УВЕРЕННОСТЬ: confidence 0.0-1.0 для каждого блока и связи
5. ЧТО НЕЯСНО: перечисли, что осталось непонятным — неразборчивый текст, неясные связи

Формат: структурированный текст."""

REFLECTOR_PROMPT = """Ты — рефлектор. Проверь результат анализа диаграммы.

## РЕЗУЛЬТАТ АГЕНТА:
{result}

## ЗАДАЧА:
1. ОЦЕНИ confidence всего результата (0.0-1.0) — одна цифра
2. НАЙДИ ПРОБЕЛЫ: что пропущено? какие блоки не описаны? какие связи не учтены?
3. НАЙДИ ПРОТИВОРЕЧИЯ: где агент мог ошибиться?
4. СФОРМУЛИРУЙ ВОПРОСЫ для следующего прохода — конкретные, с указанием области изображения

Если confidence ≥ {threshold} — напиши "ГОТОВО" и объясни почему.
Если confidence < {threshold} — напиши "ЭСКАЛАЦИЯ" и список вопросов."""

FOCUS_PROMPT = """Ты анализируешь ту же диаграмму второй раз. Рефлектор указал на проблемы в твоём предыдущем анализе.

## ВОПРОСЫ РЕФЛЕКТОРА:
{reflection}

## ТВОЙ ПРЕДЫДУЩИЙ РЕЗУЛЬТАТ:
{result}

## ЗАДАЧА:
Ответь на ВСЕ вопросы рефлектора. Если какой-то блок или связь были пропущены — добавь их.
Если рефлектор просит уточнить область — опиши её детально.
Выдай ПОЛНЫЙ обновлённый результат, не только ответы на вопросы."""


def _extract_confidence(text: str) -> float:
    """Извлекает confidence-оценку из текста рефлектора."""
    conf_match = re.search(r"confidence[:\s]*(\d+\.?\d*)", text.lower())
    if conf_match:
        return float(conf_match.group(1))
    nums = re.findall(r"(\d+\.\d+)", text)
    return float(nums[0]) if nums else 0.5


class Orchestrator:
    """Оркестратор с циклами рефлексии для анализа диаграмм."""

    def __init__(self, image_b64: str):
        self.image_b64 = image_b64
        self.iteration = 0
        self.history: list[dict] = []
        self.result: str | None = None
        self.confidence = 0.0

    def run(self, verbose: bool = True) -> tuple[str, float, list[dict]]:
        if verbose:
            print("=" * 60)
            print("MAS ОРКЕСТРАТОР С РЕФЛЕКСИЕЙ")
            print("=" * 60)

        # ── PASS 1: Agent ──
        self.iteration = 1
        if verbose:
            print(f"\n{'─' * 40}")
            print(f"PASS {self.iteration}: Agent ({AGENT_VISION_MODEL})")
            print(f"{'─' * 40}")

        t0 = time.time()
        self.result, usage = dashscope_vision(AGENT_VISION_MODEL, self.image_b64, AGENT_PROMPT)
        self.history.append({"iteration": 1, "role": "agent", "content": self.result})
        if verbose:
            print(f"  Токенов: {usage.get('total_tokens', '?')}, {time.time() - t0:.1f}s")
            print(f"  Результат: {self.result[:300]}...")

        # ── REFLECTOR → AGENT циклы ──
        for i in range(MAX_REFLECTION_ITERATIONS - 1):
            if verbose:
                print(f"\n{'─' * 40}")
                print(f"REFLECTOR {i + 1}: ({REFLECTOR_MODEL})")
                print(f"{'─' * 40}")

            t0 = time.time()
            reflector_prompt = REFLECTOR_PROMPT.format(result=self.result, threshold=CONFIDENCE_THRESHOLD)
            reflection, usage = dashscope_chat(REFLECTOR_MODEL, [{"role": "user", "content": reflector_prompt}])
            self.history.append({"iteration": self.iteration, "role": "reflector", "content": reflection})
            if verbose:
                print(f"  Токенов: {usage.get('total_tokens', '?')}, {time.time() - t0:.1f}s")
                print(f"  Рефлексия: {reflection[:400]}...")

            self.confidence = _extract_confidence(reflection)

            if "ГОТОВО" in reflection or self.confidence >= CONFIDENCE_THRESHOLD:
                if verbose:
                    print(f"\n✅ СТАБИЛИЗАЦИЯ: confidence={self.confidence}")
                break

            # ── PASS N: Agent с вопросами рефлектора ──
            self.iteration += 1
            if verbose:
                print(f"\n{'─' * 40}")
                print(f"PASS {self.iteration}: Agent (уточнение)")
                print(f"{'─' * 40}")

            t0 = time.time()
            focus_prompt = FOCUS_PROMPT.format(reflection=reflection, result=self.result)
            self.result, usage = dashscope_vision(AGENT_VISION_MODEL, self.image_b64, focus_prompt, max_tokens=8192)
            self.history.append({"iteration": self.iteration, "role": "agent", "content": self.result})
            if verbose:
                print(f"  Токенов: {usage.get('total_tokens', '?')}, {time.time() - t0:.1f}s")
                print(f"  Результат: {self.result[:300]}...")

        if verbose:
            print(f"\n{'=' * 60}")
            print(f"ИТОГ: {self.iteration} итераций, confidence={self.confidence:.2f}")
            print(f"{'=' * 60}")
            print(f"\nФИНАЛЬНЫЙ РЕЗУЛЬТАТ:\n{self.result}")

        return self.result, self.confidence, self.history

    def to_dict(self) -> dict:
        return {
            "confidence": self.confidence,
            "iterations": self.iteration,
            "history": self.history,
            "final_result": self.result,
        }

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
