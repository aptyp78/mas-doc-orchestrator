"""Sub-2: User Position Model — операционная схема стратега.

Моделирует позицию пользователя в системе деятельности:
- objectives: цели (чего хочет достичь)
- constraints: ограничения (что нельзя)
- resources: ресурсы (чем располагает)
- assumptions: допущения (во что верит)
- decision_criteria: критерии решений (как выбирает)

Интегрируется в htr_loop и doubt_gate:
- Гипотезы генерируются В КОНТЕКСТЕ позиции
- Doubt gate проверяет alignment с позицией
- Рекомендации релевантны пользователю, а не абстрактны
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"
POSITION_STORE = Path.home() / ".qwen" / "ai-canvas" / "positions"


@dataclass
class UserPosition:
    """Операционная схема пользователя-стратега."""
    user_id: str = "default"
    objectives: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    decision_criteria: list[str] = field(default_factory=list)
    domain: str = ""  # проблемная область
    role: str = ""  # роль в организации
    updated_at: str = ""

    def __post_init__(self):
        if not self.updated_at:
            self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_context(self) -> str:
        """Форматирует позицию для подстановки в промпт."""
        parts = []
        if self.objectives:
            parts.append(f"Цели: {'; '.join(self.objectives)}")
        if self.constraints:
            parts.append(f"Ограничения: {'; '.join(self.constraints)}")
        if self.resources:
            parts.append(f"Ресурсы: {'; '.join(self.resources)}")
        if self.assumptions:
            parts.append(f"Допущения: {'; '.join(self.assumptions)}")
        if self.decision_criteria:
            parts.append(f"Критерии решений: {'; '.join(self.decision_criteria)}")
        if self.domain:
            parts.append(f"Домен: {self.domain}")
        if self.role:
            parts.append(f"Роль: {self.role}")
        return "\n".join(parts)

    def is_empty(self) -> bool:
        return not any([
            self.objectives, self.constraints, self.resources,
            self.assumptions, self.decision_criteria,
        ])

    def save(self):
        POSITION_STORE.mkdir(parents=True, exist_ok=True)
        path = POSITION_STORE / f"{self.user_id}.json"
        with open(path, "w") as f:
            json.dump({
                "user_id": self.user_id,
                "objectives": self.objectives,
                "constraints": self.constraints,
                "resources": self.resources,
                "assumptions": self.assumptions,
                "decision_criteria": self.decision_criteria,
                "domain": self.domain,
                "role": self.role,
                "updated_at": self.updated_at,
            }, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, user_id: str = "default") -> "UserPosition":
        path = POSITION_STORE / f"{user_id}.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            return cls(
                user_id=data.get("user_id", user_id),
                objectives=data.get("objectives", []),
                constraints=data.get("constraints", []),
                resources=data.get("resources", []),
                assumptions=data.get("assumptions", []),
                decision_criteria=data.get("decision_criteria", []),
                domain=data.get("domain", ""),
                role=data.get("role", ""),
                updated_at=data.get("updated_at", ""),
            )
        return cls(user_id=user_id)


def _call_ollama(prompt: str, max_tokens: int = 1024) -> str:
    data = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.1, "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat", data=data,
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


class PositionExtractor:
    """Извлекает позицию пользователя из диалога."""

    PROMPT = """[РОЛЬ] Экстрактор операционной схемы стратега
[ПРЕДМЕТ] Ответ пользователя на вопросы о его позиции
[ЗАДАЧА] Извлеки структурированную операционную схему
[ПРАВИЛА]
1. objectives: конкретные цели (измеримые, если указаны)
2. constraints: жёсткие ограничения (что нельзя делать)
3. resources: доступные ресурсы (люди, деньги, время, связи)
4. assumptions: во что пользователь верит о ситуации
5. decision_criteria: по каким критериям выбирает между вариантами
6. Если что-то не указано — оставь пустым массивом
[ОГРАНИЧЕНИЕ] Извлекай только то, что явно сказано. Не домысливай.

Формат: JSON
{{
  "objectives": ["string"],
  "constraints": ["string"],
  "resources": ["string"],
  "assumptions": ["string"],
  "decision_criteria": ["string"]
}}

## ОТВЕТ ПОЛЬЗОВАТЕЛЯ
{user_response}"""

    def extract(self, user_response: str) -> dict:
        prompt = self.PROMPT.format(user_response=user_response[:2000])
        return _parse_json(_call_ollama(prompt, max_tokens=1024))


class PositionAligner:
    """Проверяет alignment рекомендации с позицией пользователя."""

    PROMPT = """[РОЛЬ] Контролёр alignment рекомендации с позицией
[ПРЕДМЕТ] Рекомендация + операционная схема стратега
[ЗАДАЧА] Проверь, насколько рекомендация соответствует позиции
[ПРАВИЛА]
1. Проверь соответствие целям (objectives)
2. Проверь нарушение ограничений (constraints)
3. Проверь достаточность ресурсов (resources)
4. Проверь соответствие критериям (decision_criteria)
5. Оцени alignment: 0.0-1.0
[ОГРАНИЧЕНИЕ] Будь строг. Если рекомендация требует ресурсов, которых нет — alignment низкий.

Формат: JSON
{{
  "alignment_score": 0.0-1.0,
  "matches_objectives": ["string"],
  "violates_constraints": ["string"],
  "resource_gaps": ["string"],
  "verdict": "aligned|partial|misaligned"
}}

## РЕКОМЕНДАЦИЯ
{recommendation}

## ПОЗИЦИЯ
{position}"""

    def check(self, recommendation: str, position: UserPosition) -> dict:
        if position.is_empty():
            return {"alignment_score": 0.5, "verdict": "partial", "note": "position not specified"}
        prompt = self.PROMPT.format(
            recommendation=recommendation[:1000],
            position=position.to_context(),
        )
        return _parse_json(_call_ollama(prompt, max_tokens=512))