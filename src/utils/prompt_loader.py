"""Система загрузки промптов из файлов.

Все промпты хранятся в prompts/*.md и загружаются через эту систему.
Никакие промпты не встраиваются в код — только импортируются из файлов.

Использование:
    from src.utils.prompt_loader import load_prompt
    
    classifier_prompt = load_prompt("semiotic/classifier")
    ontology_prompt = load_prompt("semiotic/ontology")
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

# Базовая директория для промптов
PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(prompt_path: str) -> str:
    """Загружает промпт из файла.
    
    Args:
        prompt_path: путь к промпту относительно prompts/ (без расширения .md)
                     Например: "semiotic/classifier", "orchestrator/domain_analyzer"
    
    Returns:
        Содержимое промпта как строка
    
    Raises:
        FileNotFoundError: если файл не найден
    """
    file_path = PROMPTS_DIR / f"{prompt_path}.md"
    
    if not file_path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {file_path}\n"
            f"Expected at: {PROMPTS_DIR}/{prompt_path}.md"
        )
    
    return file_path.read_text(encoding="utf-8")


def list_prompts() -> list[str]:
    """Возвращает список всех доступных промптов.
    
    Returns:
        Список путей к промптам относительно prompts/ (без расширения .md)
    """
    prompts = []
    for md_file in PROMPTS_DIR.rglob("*.md"):
        # Пропускаем служебные файлы
        if md_file.name in ("README.md", "CHANGELOG.md", "AUDIT.md"):
            continue
        
        # Вычисляем относительный путь
        rel_path = md_file.relative_to(PROMPTS_DIR)
        prompt_path = str(rel_path.with_suffix(""))
        prompts.append(prompt_path)
    
    return sorted(prompts)


def get_prompt_version(prompt_path: str) -> str:
    """Возвращает версию промпта из CHANGELOG.md.
    
    Args:
        prompt_path: путь к промпту относительно prompts/
    
    Returns:
        Версия промпта или "unknown"
    """
    changelog_path = PROMPTS_DIR / "CHANGELOG.md"
    if not changelog_path.exists():
        return "unknown"
    
    # TODO: Парсить CHANGELOG.md для получения версии конкретного промпта
    return "unknown"
