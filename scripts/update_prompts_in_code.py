#!/usr/bin/env python3
"""Скрипт для обновления кода: замена встроенных промптов на load_prompt()."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Маппинг: (файл, [(prompt_name, prompt_path), ...])
UPDATE_MAP = {
    "src/semiotic/extractors.py": [
        ("VENN_PROMPT", "semiotic/extractors_venn"),
        ("HIERARCHY_PROMPT", "semiotic/extractors_hierarchy"),
        ("MATRIX_PROMPT", "semiotic/extractors_matrix"),
        ("ENUMERATION_PROMPT", "semiotic/extractors_enumeration"),
    ],
    "src/semiotic/ontology.py": [
        ("ONTOLOGY_PROMPT", "semiotic/ontology"),
    ],
    "src/semiotic/reflector.py": [
        ("REFLECTOR_PROMPT", "semiotic/reflector"),
    ],
    "src/semiotic/cloud_classifier.py": [
        ("SEMIOTIC_PROMPT", "semiotic/cloud_classifier"),
    ],
    "src/semiotic/cloud_ontology.py": [
        ("ONTOLOGY_PROMPT", "semiotic/cloud_ontology"),
    ],
    "src/semiotic/cloud_reflector.py": [
        ("REFLECTOR_PROMPT", "semiotic/cloud_reflector"),
    ],
    "src/semiotic/mixed_decomposer.py": [
        ("DECOMPOSE_PROMPT", "semiotic/mixed_decomposer"),
    ],
    "src/orchestrator/domain_analyzer.py": [
        ("DOMAIN_ANALYSIS_PROMPT", "orchestrator/domain_analyzer"),
    ],
    "src/orchestrator/temporal_linker.py": [
        ("PAIR_PROMPT", "orchestrator/temporal_linker_pair"),
        ("CHAIN_PROMPT", "orchestrator/temporal_linker_chain"),
    ],
    "src/orchestrator/doubt_gate.py": [
        ("ASSESS_PROMPT", "orchestrator/doubt_gate_assess"),
    ],
    "src/orchestrator/engine.py": [
        ("AGENT_PROMPT", "engine/agent"),
        ("REFLECTOR_PROMPT", "engine/reflector"),
        ("FOCUS_PROMPT", "engine/focus"),
    ],
    "src/orchestrator/cross_page_synthesizer.py": [
        ("PAIR_PROMPT", "orchestrator/cross_page_synthesizer_pair"),
        ("GLOBAL_PROMPT", "orchestrator/cross_page_synthesizer_global"),
    ],
    "src/orchestrator/cross_page_linker.py": [
        ("VERIFY_PROMPT", "orchestrator/cross_page_linker_verify"),
    ],
    "src/normalizer/pdf_normalizer.py": [
        ("ZONE_SEPARATION_PROMPT", "normalizer/zone_separator"),
        ("IMAGE_CONTENT_PROMPT", "normalizer/image_content_extractor"),
    ],
    "src/normalizer/vl_normalizer.py": [
        ("VL_PARSE_PROMPT", "normalizer/vl_parse"),
    ],
    "src/dream_agent.py": [
        ("DREAM_PROMPT", "dream_agent"),
    ],
}


def update_file(file_path: str, prompts: list[tuple[str, str]]) -> bool:
    """Обновляет файл: заменяет встроенные промпты на load_prompt()."""
    path = Path(file_path)
    if not path.exists():
        print(f"  ❌ Файл не найден: {file_path}")
        return False
    
    content = path.read_text(encoding="utf-8")
    original_content = content
    
    # Добавляем импорт prompt_loader, если его нет
    if "from src.utils.prompt_loader import load_prompt" not in content:
        # Находим последний import и добавляем после него
        import_pattern = r'(from\s+\S+\s+import\s+[^\n]+\n)'
        matches = list(re.finditer(import_pattern, content))
        if matches:
            last_import = matches[-1]
            insert_pos = last_import.end()
            content = (
                content[:insert_pos] +
                "from src.utils.prompt_loader import load_prompt\n" +
                content[insert_pos:]
            )
    
    # Заменяем встроенные промпты на load_prompt()
    for prompt_name, prompt_path in prompts:
        # Паттерн: PROMPT_NAME = """..."""
        pattern = rf'{prompt_name}\s*=\s*"""(.*?)"""'
        replacement = f'{prompt_name} = load_prompt("{prompt_path}")'
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Сохраняем, если были изменения
    if content != original_content:
        path.write_text(content, encoding="utf-8")
        print(f"  ✅ Обновлён: {file_path}")
        return True
    else:
        print(f"  ⚠️  Без изменений: {file_path}")
        return False


def main():
    print("Обновление кода для использования load_prompt()...")
    print("=" * 60)
    
    total = 0
    success = 0
    
    for file_path, prompts in UPDATE_MAP.items():
        print(f"\n📄 {file_path}")
        
        for prompt_name, prompt_path in prompts:
            total += 1
        
        if update_file(file_path, prompts):
            success += len(prompts)
    
    print("\n" + "=" * 60)
    print(f"✅ Обновлено: {success}/{total} промптов")
    
    return success == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
