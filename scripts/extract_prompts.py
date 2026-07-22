#!/usr/bin/env python3
"""Скрипт для автоматического извлечения промптов из кода в prompts/*.md."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Маппинг файлов и промптов
PROMPT_MAP = {
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


def extract_prompt(file_path: str, prompt_name: str) -> str | None:
    """Извлекает промпт из файла по имени переменной."""
    path = Path(file_path)
    if not path.exists():
        print(f"  ❌ Файл не найден: {file_path}")
        return None
    
    content = path.read_text(encoding="utf-8")
    
    # Паттерн для поиска промпта: PROMPT_NAME = """..."""
    pattern = rf'{prompt_name}\s*=\s*"""(.*?)"""'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        print(f"  ❌ Промпт {prompt_name} не найден в {file_path}")
        return None
    
    return match.group(1).strip()


def save_prompt(prompt_content: str, prompt_path: str) -> bool:
    """Сохраняет промпт в файл."""
    file_path = Path("prompts") / f"{prompt_path}.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    file_path.write_text(prompt_content, encoding="utf-8")
    print(f"  ✅ Сохранён: {file_path} ({len(prompt_content)} chars)")
    return True


def main():
    print("Извлечение промптов из кода...")
    print("=" * 60)
    
    total = 0
    success = 0
    
    for file_path, prompts in PROMPT_MAP.items():
        print(f"\n📄 {file_path}")
        
        for prompt_name, prompt_path in prompts:
            total += 1
            prompt_content = extract_prompt(file_path, prompt_name)
            
            if prompt_content:
                if save_prompt(prompt_content, prompt_path):
                    success += 1
    
    print("\n" + "=" * 60)
    print(f"✅ Извлечено: {success}/{total} промптов")
    
    if success < total:
        print(f"⚠️  Не удалось извлечь: {total - success} промптов")
    
    return success == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
