"""Sub-4: Action Loop — замкнутый цикл: рекомендация → действие → результат → коррекция.

Замыкает разрыв между «система даёт рекомендацию» и «реальность реагирует».
- ActionState: recommended → implemented → outcome → learned
- FeedbackCollector: собирает обратную связь от пользователя
- PriorUpdater: обновляет priors в htr_loop на основе исходов
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"
FEEDBACK_STORE = Path.home() / ".qwen" / "ai-canvas" / "feedback"


class ActionStatus(Enum):
    RECOMMENDED = auto()   # Рекомендация выдана
    ACCEPTED = auto()      # Принята к исполнению
    IMPLEMENTED = auto()   # Реализована
    BLOCKED = auto()       # Заблокирована
    ABANDONED = auto()     # Отклонена
    SUCCEEDED = auto()     # Успешный исход
    FAILED = auto()        # Неудачный исход


@dataclass
class ActionRecord:
    """Запись о действии."""
    action_id: str
    recommendation: str
    page_source: int
    status: ActionStatus = ActionStatus.RECOMMENDED
    outcome: str = ""  # что произошло
    user_feedback: str = ""  # комментарий пользователя
    lessons: list[str] = field(default_factory=list)  # извлечённые уроки
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.created_at:
            self.created_at = ts
        if not self.updated_at:
            self.updated_at = ts


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
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["message"]["content"]


def _parse_json(text: str) -> dict:
    try:
        j1, j2 = text.find("{"), text.rfind("}") + 1
        if j1 >= 0 and j2 > j1:
            return json.loads(text[j1:j2])
    except (json.JSONDecodeError, KeyError):
        pass
    return {}


class PriorUpdater:
    """Обновляет priors в htr_loop на основе исходов действий."""

    PROMPT = """[РОЛЬ] Аналитик обратной связи
[ПРЕДМЕТ] Исход реализованной рекомендации + исходная гипотеза
[ЗАДАЧА] Извлеки уроки и обнови confidence-оценки
[ПРАВИЛА]
1. Что подтвердилось? (evidence FOR hypothesis)
2. Что опровергнуто? (evidence AGAINST hypothesis)
3. Какие допущения оказались неверными?
4. Как скорректировать confidence?
5. Что нужно проверить в следующей итерации?
[ОГРАНИЧЕНИЕ] Честно. Если исход не подтверждает гипотезу — снизь confidence.

Формат: JSON
{{
  "confirmed": ["string"],
  "refuted": ["string"],
  "wrong_assumptions": ["string"],
  "adjusted_confidence": 0.0-1.0,
  "next_check": "string"
}}

## РЕКОМЕНДАЦИЯ
{recommendation}

## ИСХОД
{outcome}

## ПОЛЬЗОВАТЕЛЬ
{feedback}"""

    def update(self, recommendation: str, outcome: str, user_feedback: str) -> dict:
        prompt = self.PROMPT.format(
            recommendation=recommendation[:1000],
            outcome=outcome[:500],
            feedback=user_feedback[:500],
        )
        return _parse_json(_call_ollama(prompt, max_tokens=512))


class ActionLoop:
    """Замкнутый цикл: рекомендация → действие → результат → коррекция."""

    def __init__(self):
        self.updater = PriorUpdater()
        self.records: list[ActionRecord] = []
        FEEDBACK_STORE.mkdir(parents=True, exist_ok=True)

    def recommend(self, action: str, page_source: int) -> ActionRecord:
        """Фиксирует новую рекомендацию."""
        record = ActionRecord(
            action_id=f"act_{int(time.time())}_{page_source}",
            recommendation=action,
            page_source=page_source,
        )
        self.records.append(record)
        return record

    def feedback(self, action_id: str, status: ActionStatus, outcome: str = "",
                 user_feedback: str = "") -> ActionRecord | None:
        """Принимает обратную связь по действию."""
        for r in self.records:
            if r.action_id == action_id:
                r.status = status
                r.outcome = outcome
                r.user_feedback = user_feedback
                r.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

                # Извлекаем уроки
                if outcome:
                    lessons = self.updater.update(r.recommendation, outcome, user_feedback)
                    r.lessons = lessons.get("confirmed", []) + lessons.get("refuted", [])

                self._save(r)
                return r
        return None

    def _save(self, record: ActionRecord):
        path = FEEDBACK_STORE / f"{record.action_id}.json"
        with open(path, "w") as f:
            json.dump({
                "action_id": record.action_id,
                "recommendation": record.recommendation,
                "page_source": record.page_source,
                "status": record.status.name,
                "outcome": record.outcome,
                "user_feedback": record.user_feedback,
                "lessons": record.lessons,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }, f, ensure_ascii=False, indent=2)

    def get_learned_priors(self) -> dict:
        """Возвращает накопленные уроки для обновления htr_loop."""
        all_lessons = []
        for r in self.records:
            if r.lessons:
                all_lessons.extend(r.lessons)

        # Считаем частоту уроков
        from collections import Counter
        lesson_counts = Counter(all_lessons)
        top_lessons = [l for l, _ in lesson_counts.most_common(10)]

        return {
            "total_actions": len(self.records),
            "implemented": sum(1 for r in self.records if r.status == ActionStatus.IMPLEMENTED),
            "succeeded": sum(1 for r in self.records if r.status == ActionStatus.SUCCEEDED),
            "top_lessons": top_lessons,
        }

    def list_actions(self) -> list[dict]:
        return [
            {
                "action_id": r.action_id,
                "recommendation": r.recommendation[:150],
                "status": r.status.name,
                "page": r.page_source,
            }
            for r in self.records
        ]