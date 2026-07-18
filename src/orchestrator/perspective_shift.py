"""Sub-1: Perspective Shift — принудительная смена формата представления проблемы.

Не просто advocate/skeptic (аргументы ЗА/ПРОТИВ), а смена самой системы координат:
- Text → Spatial (ментальная карта: кто где, зоны влияния)
- Static → Temporal (временная шкала: что было → что будет)
- Analytic → Synthetic (целостный взгляд: система в целом, emergent properties)
- Quantitative → Qualitative (нарратив: история, смысл, а не цифры)

Использует локальную Ollama (qwen3.6:35b).
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum, auto

from src.utils.config import OLLAMA_LOCAL_BASE

MODEL = "qwen3.6:35b"


class PerspectiveType(Enum):
    SPATIAL = auto()      # Пространственная: ментальная карта
    TEMPORAL = auto()     # Временная: шкала, последовательность
    SYSTEMIC = auto()     # Системная: целостный взгляд
    NARRATIVE = auto()    # Нарративная: история, смысл


@dataclass
class Perspective:
    """Альтернативное представление проблемы."""
    perspective_type: PerspectiveType
    representation: str  # текстовое описание нового представления
    insights: list[str]  # что нового видно под этим углом
    blind_spots: list[str]  # что теряется при таком взгляде
    action_implications: list[str]  # какие действия следуют из этого взгляда


@dataclass
class PerspectiveShiftResult:
    """Результат сдвига перспективы."""
    original_question: str
    original_context: str
    perspectives: list[Perspective] = field(default_factory=list)
    synthesis: str = ""  # синтез всех перспектив
    dominant_perspective: PerspectiveType | None = None


def _call_ollama(prompt: str, max_tokens: int = 2048) -> str:
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


class PerspectiveShiftAgent:
    """Генерирует альтернативные представления одной и той же проблемы."""

    PROMPT = """[РОЛЬ] Оператор сдвига перспективы (СМД-методология)
[ПРЕДМЕТ] Проблема/вопрос + контекст документа
[ЗАДАЧА] Представь проблему в 4 разных системах координат. Это НЕ аргументы за/против — это РАЗНЫЕ СПОСОБЫ ВИДЕТЬ.
[ПРАВИЛА]
1. SPATIAL: нарисуй ментальную карту — кто где находится? Какие зоны влияния? Что с чем граничит?
2. TEMPORAL: построй временную шкалу — что было раньше? Что будет потом? Где точка невозврата?
3. SYSTEMIC: посмотри на систему целиком — какие emergent properties? Какие петли обратной связи?
4. NARRATIVE: расскажи историю — в чём драма? Кто герой? Какой сюжет?
5. Для каждой перспективы: insights (что видно), blind_spots (что теряется), action_implications (что делать)
6. SYNTHESIS: какой взгляд доминирует? Почему?
[ОГРАНИЧЕНИЕ] Не оценивай перспективы как «правильные/неправильные». Каждая частична. Синтез — в их пересечении.

Формат: JSON
{{
  "perspectives": [
    {{
      "type": "spatial",
      "representation": "string — текстовое описание ментальной карты",
      "insights": ["string"],
      "blind_spots": ["string"],
      "action_implications": ["string"]
    }},
    {{
      "type": "temporal",
      "representation": "string",
      "insights": ["string"],
      "blind_spots": ["string"],
      "action_implications": ["string"]
    }},
    {{
      "type": "systemic",
      "representation": "string",
      "insights": ["string"],
      "blind_spots": ["string"],
      "action_implications": ["string"]
    }},
    {{
      "type": "narrative",
      "representation": "string",
      "insights": ["string"],
      "blind_spots": ["string"],
      "action_implications": ["string"]
    }}
  ],
  "synthesis": "string — какой взгляд доминирует и почему",
  "dominant_perspective": "spatial|temporal|systemic|narrative"
}}

## ВОПРОС
{question}

## КОНТЕКСТ
{context}"""

    def shift(self, question: str, context: str) -> PerspectiveShiftResult:
        """Выполняет сдвиг перспективы."""
        t0 = time.time()

        prompt = self.PROMPT.format(question=question, context=context[:5000])
        result = _parse_json(_call_ollama(prompt, max_tokens=3072))

        perspectives = []
        for p in result.get("perspectives", []):
            ptype_str = p.get("type", "spatial")
            ptype_map = {
                "spatial": PerspectiveType.SPATIAL,
                "temporal": PerspectiveType.TEMPORAL,
                "systemic": PerspectiveType.SYSTEMIC,
                "narrative": PerspectiveType.NARRATIVE,
            }
            perspectives.append(Perspective(
                perspective_type=ptype_map.get(ptype_str, PerspectiveType.SPATIAL),
                representation=p.get("representation", ""),
                insights=p.get("insights", []),
                blind_spots=p.get("blind_spots", []),
                action_implications=p.get("action_implications", []),
            ))

        dom_str = result.get("dominant_perspective", "systemic")
        dom_map = {
            "spatial": PerspectiveType.SPATIAL, "temporal": PerspectiveType.TEMPORAL,
            "systemic": PerspectiveType.SYSTEMIC, "narrative": PerspectiveType.NARRATIVE,
        }

        elapsed = time.time() - t0
        print(f"  [PERSPECTIVE_SHIFT] {len(perspectives)} perspectives, dominant={dom_str} — {elapsed:.1f}s")

        return PerspectiveShiftResult(
            original_question=question,
            original_context=context[:500],
            perspectives=perspectives,
            synthesis=result.get("synthesis", ""),
            dominant_perspective=dom_map.get(dom_str),
        )

    def to_dict(self, result: PerspectiveShiftResult) -> dict:
        return {
            "question": result.original_question,
            "perspectives": [
                {
                    "type": p.perspective_type.name,
                    "representation": p.representation,
                    "insights": p.insights,
                    "blind_spots": p.blind_spots,
                    "action_implications": p.action_implications,
                }
                for p in result.perspectives
            ],
            "synthesis": result.synthesis,
            "dominant_perspective": result.dominant_perspective.name if result.dominant_perspective else None,
        }

    def format_for_cli(self, result: PerspectiveShiftResult) -> str:
        """Форматирует для вывода в терминал."""
        lines = ["\n🔄 PERSPECTIVE SHIFT", "=" * 50]
        for p in result.perspectives:
            icon = {"SPATIAL": "🗺", "TEMPORAL": "⏳", "SYSTEMIC": "🔮", "NARRATIVE": "📖"}.get(p.perspective_type.name, "•")
            lines.append(f"\n{icon} {p.perspective_type.name}")
            lines.append(f"   {p.representation[:200]}")
            if p.insights:
                lines.append(f"   💡 Видно: {p.insights[0][:150]}")
            if p.blind_spots:
                lines.append(f"   🕳 Слепое пятно: {p.blind_spots[0][:150]}")
        lines.append(f"\n🔗 СИНТЕЗ: {result.synthesis[:300]}")
        return "\n".join(lines)