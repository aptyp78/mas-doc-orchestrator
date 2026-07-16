"""Шаг 4: Strategic Dialogue Mediator — диалоговый движок стратегического мышления.

Вместо монолога (отчёт → готовый ответ) — многопозиционная аргументация:
- CounterPositionAgent: симулирует роли adversary/partner
- DialogueOrchestrator: генерирует 2-3 альтернативные стратегии с аргументами за/против
- Состояние диалога с fading relevance

Использует локальную Ollama (qwen3.6:35b).
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from collections import OrderedDict

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"
MAX_DIALOGUE_HISTORY = 10


@dataclass
class Position:
    """Стратегическая позиция."""
    role: str  # "advocate" | "skeptic" | "synthesizer"
    statement: str
    arguments: list[str] = field(default_factory=list)
    counterarguments: list[str] = field(default_factory=list)
    confidence: float = 0.5


@dataclass
class DialogueTurn:
    """Один ход диалога."""
    turn_id: int
    role: str
    content: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%H:%M:%S")


@dataclass
class DialogueState:
    """Состояние стратегического диалога."""
    topic: str
    positions: list[Position] = field(default_factory=list)
    history: list[DialogueTurn] = field(default_factory=list)
    resolution: str = ""
    consensus_reached: bool = False


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


class CounterPositionAgent:
    """Генерирует альтернативные позиции: advocate, skeptic, synthesizer."""

    PROMPT = """[РОЛЬ] Генератор стратегических позиций
[ПРЕДМЕТ] Рекомендация + онтология страницы
[ЗАДАЧА] Сгенерируй 3 позиции по отношению к рекомендации:
1. ADVOCATE (адвокат): почему это правильное решение
2. SKEPTIC (скептик): почему это рискованно / не сработает
3. SYNTHESIZER (синтезатор): компромиссный вариант, учитывающий обе стороны
[ПРАВИЛА]
- Каждая позиция: statement (1 предложение), 2-3 arguments, 2-3 counterarguments
- confidence: насколько позиция обоснована онтологией
- Позиции должны быть РАЗЛИЧНЫМИ, не вариациями
[ОГРАНИЧЕНИЕ] На основе онтологии. Не выдумывай факты.

Формат: JSON
{{
  "positions": [
    {{
      "role": "advocate",
      "statement": "string",
      "arguments": ["string"],
      "counterarguments": ["string"],
      "confidence": 0.0-1.0
    }},
    {{
      "role": "skeptic",
      "statement": "string",
      "arguments": ["string"],
      "counterarguments": ["string"],
      "confidence": 0.0-1.0
    }},
    {{
      "role": "synthesizer",
      "statement": "string",
      "arguments": ["string"],
      "counterarguments": ["string"],
      "confidence": 0.0-1.0
    }}
  ]
}}

## ОНТОЛОГИЯ
{ontology}

## РЕКОМЕНДАЦИЯ
{recommendation}"""

    def generate(self, ontology: dict, recommendation: dict) -> list[Position]:
        """Генерирует альтернативные позиции."""
        ont_str = json.dumps(ontology, ensure_ascii=False)[:2000]
        refl_str = json.dumps(recommendation, ensure_ascii=False)[:1000]

        prompt = self.PROMPT.format(ontology=ont_str, recommendation=refl_str)
        result = _parse_json(_call_ollama(prompt, max_tokens=1024))

        positions = []
        for p in result.get("positions", []):
            positions.append(Position(
                role=p.get("role", "advocate"),
                statement=p.get("statement", ""),
                arguments=p.get("arguments", []),
                counterarguments=p.get("counterarguments", []),
                confidence=p.get("confidence", 0.5),
            ))
        return positions


class DialogueOrchestrator:
    """Управляет стратегическим диалогом."""

    def __init__(self):
        self.counter_agent = CounterPositionAgent()
        self.active_dialogues: OrderedDict[str, DialogueState] = OrderedDict()

    def start_dialogue(self, topic_id: str, ontology: dict, recommendation: dict) -> DialogueState:
        """Начинает диалог по рекомендации."""
        positions = self.counter_agent.generate(ontology, recommendation)

        state = DialogueState(
            topic=f"p{topic_id}: {recommendation.get('recommended_action', '')[:100]}",
            positions=positions,
        )
        state.history.append(DialogueTurn(
            turn_id=0,
            role="system",
            content=f"Диалог открыт: {state.topic}",
        ))

        # Добавляем позиции как первые ходы
        for i, pos in enumerate(positions):
            state.history.append(DialogueTurn(
                turn_id=i + 1,
                role=pos.role,
                content=f"[{pos.role.upper()}] {pos.statement}\n"
                        f"За: {'; '.join(pos.arguments[:2])}\n"
                        f"Против: {'; '.join(pos.counterarguments[:2])}",
            ))

        self.active_dialogues[topic_id] = state

        # Ограничиваем размер
        while len(self.active_dialogues) > MAX_DIALOGUE_HISTORY:
            self.active_dialogues.popitem(last=False)

        return state

    def get_dialogue_summary(self, topic_id: str) -> str:
        """Возвращает сводку диалога."""
        state = self.active_dialogues.get(topic_id)
        if not state:
            return "Диалог не найден."

        lines = [f"## {state.topic}"]
        for turn in state.history:
            lines.append(f"[{turn.role}] {turn.content[:200]}")

        if state.consensus_reached:
            lines.append(f"\n✅ Консенсус: {state.resolution}")
        else:
            lines.append(f"\n🔄 Диалог продолжается. Позиции: {len(state.positions)}")

        return "\n".join(lines)

    def get_active_topics(self) -> list[str]:
        return list(self.active_dialogues.keys())

    def to_dict(self) -> dict:
        return {
            "active_dialogues": len(self.active_dialogues),
            "topics": [
                {
                    "topic_id": tid,
                    "topic": state.topic,
                    "positions": [
                        {"role": p.role, "statement": p.statement, "confidence": p.confidence}
                        for p in state.positions
                    ],
                    "consensus_reached": state.consensus_reached,
                    "turns": len(state.history),
                }
                for tid, state in self.active_dialogues.items()
            ],
        }