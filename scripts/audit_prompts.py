#!/usr/bin/env python3
"""Аудит промптов: проверка формата [РОЛЬ]...[ОГРАНИЧЕНИЕ], JSON-схем, метрик.

Использование:
  python3 scripts/audit_prompts.py              # аудит всех промптов
  python3 scripts/audit_prompts.py prompts/engine/agent.md  # аудит одного
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Правила проверки
RULES = {
    "role_format": {
        "description": "Формат [РОЛЬ]...[ОГРАНИЧЕНИЕ]",
        "check": lambda content: bool(re.search(r"\[РОЛЬ\].*\[ОГРАНИЧЕНИЕ\]", content, re.DOTALL)),
    },
    "no_anthropomorph": {
        "description": "Нет «Ты — эксперт/агент»",
        "check": lambda content: not re.search(r"Ты\s*—\s*(эксперт|агент|методолог|специалист)", content),
    },
    "json_schema": {
        "description": "Есть JSON-схема вывода",
        "check": lambda content: bool(re.search(r"\{[\s\S]*?\"[a-z_]+\"[\s\S]*?:[\s\S]*?\"[A-Za-z|]+\"", content)),
    },
    "no_float_confidence": {
        "description": "Нет требований float confidence (0.0-1.0)",
        "check": lambda content: not re.search(r"confidence[\s\S]*?0\.\d|0\.\d[\s\S]*?confidence", content),
    },
    "has_version": {
        "description": "Указана версия в заголовке",
        "check": lambda content: bool(re.search(r"\*\*Версия:\*\*\s*\d+\.\d+", content)),
    },
    "has_model": {
        "description": "Указана модель",
        "check": lambda content: bool(re.search(r"\*\*Модель:\*\*", content)),
    },
}


def audit_prompt(filepath: Path) -> dict:
    """Проверяет один промпт-файл."""
    content = filepath.read_text()

    result = {"file": str(filepath.relative_to(PROMPTS_DIR.parent)), "violations": [], "passed": []}

    for rule_name, rule in RULES.items():
        if rule["check"](content):
            result["passed"].append(rule_name)
        else:
            result["violations"].append(rule_name)

    return result


def audit_all() -> dict:
    """Аудит всех промптов в директории."""
    results = []
    for root, dirs, files in os.walk(PROMPTS_DIR):
        for fname in sorted(files):
            if fname.endswith(".md") and fname not in ("README.md", "CHANGELOG.md", "AUDIT.md"):
                result = audit_prompt(Path(root) / fname)
                results.append(result)

    passed_all = sum(1 for r in results if not r["violations"])
    total = len(results)

    return {"results": results, "total": total, "passed_all": passed_all, "failed": total - passed_all}


def main():
    if len(sys.argv) > 1:
        # Аудит одного файла
        filepath = Path(sys.argv[1]).resolve()
        if not filepath.exists():
            print(f"ERROR: {filepath} not found")
            sys.exit(1)
        result = audit_prompt(filepath)
        print(f"\n{'='*50}")
        print(f"АУДИТ: {result['file']}")
        print(f"{'='*50}")
        if result["violations"]:
            print(f"❌ Нарушения: {', '.join(result['violations'])}")
        else:
            print("✅ Все правила соблюдены")
        print(f"✅ Пройдено: {', '.join(result['passed'])}")
        sys.exit(1 if result["violations"] else 0)

    # Аудит всех
    report = audit_all()
    print(f"\n{'='*50}")
    print(f"АУДИТ ПРОМПТОВ: {report['total']} файлов")
    print(f"{'='*50}")

    for r in report["results"]:
        status = "❌" if r["violations"] else "✅"
        fname = os.path.basename(r["file"])
        if r["violations"]:
            print(f"  {status} {fname}: {', '.join(r['violations'])}")
        else:
            print(f"  {status} {fname}")

    print(f"\nИтого: {report['passed_all']}/{report['total']} без нарушений")
    if report["failed"] > 0:
        print(f"Нарушения в {report['failed']} файлах")
        sys.exit(1)


if __name__ == "__main__":
    main()