"""Операционно-ролевые позиции (ОРП) для MAS Orchestrator.

Каждая роль — замкнутая единица деятельности:
- Имеет заявление роли (операционно-ролевую позицию)
- Принимает входной контракт
- Отдаёт выходной контракт
- Не вызывает другие роли напрямую

Координация — через Dispatcher.
"""

from __future__ import annotations

from typing import Protocol


class Role(Protocol):
    """Протокол роли: run(вход) → выход."""

    ROLE: str  # Заявление роли
    PROMPT: str  # Промпт-шаблон

    def run(self, **kwargs) -> dict: ...
