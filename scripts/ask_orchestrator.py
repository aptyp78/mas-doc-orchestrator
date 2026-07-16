#!/usr/bin/env python3
"""C-level Q&A диспетчер — оркестратор стратегического диалога.

Принимает вопрос на естественном языке, загружает данные последнего прогона,
маршрутизирует через режимы оркестрации и возвращает структурированный ответ
с provenance, doubt-оценкой и multi-position аргументацией.

Запуск:
  python3 scripts/ask_orchestrator.py "Какие риски для России в Африке?"
  python3 scripts/ask_orchestrator.py --run output/run_2026-07-15_1107 "Почему рекомендация по олову?"
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import OLLAMA_LOCAL_BASE
from src.orchestrator.provenance import ProvenanceMapper
from src.orchestrator.doubt_gate import MetaCognitiveReflector
from src.orchestrator.dialogue_mediator import DialogueOrchestrator
from src.orchestrator.zone_store import ZoneStore
from src.orchestrator.cross_page_linker import CrossPageLinker

# Глобальные кэши (ленивая инициализация)
_zone_store: ZoneStore | None = None
_cross_page_linker: CrossPageLinker | None = None
_cached_run_dir: str = ""

MODEL = "qwen3.6:35b"


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


def _find_latest_run() -> str:
    runs = sorted(Path("output").glob("run_*"))
    if not runs:
        print("❌ Нет run-директорий. Запустите pipeline: python3 scripts/run_cloud_pipeline.py <pdf>")
        sys.exit(1)
    return str(runs[-1])


def _load_data(run_dir: str) -> dict:
    """Загружает все данные прогона."""
    data = {}

    # Схемы
    schemas_path = f"{run_dir}/03_schemas.json"
    if Path(schemas_path).exists():
        with open(schemas_path) as f:
            raw = json.load(f)
        data["schemas"] = {int(k): v for k, v in raw.items()} if isinstance(raw, dict) else {s["page_id"]: s for s in raw}

    # Рекомендации
    recs_path = f"{run_dir}/07_recommendations.json"
    if Path(recs_path).exists():
        with open(recs_path) as f:
            data["recommendations"] = json.load(f)

    # Классификация
    class_path = f"{run_dir}/01_semiotic_classification.json"
    if Path(class_path).exists():
        with open(class_path) as f:
            data["classification"] = json.load(f)

    return data


def _init_zone_store(run_dir: str) -> ZoneStore:
    """Инициализирует ZoneStore с кэшированием."""
    global _zone_store, _cross_page_linker, _cached_run_dir
    if _zone_store is not None and _cached_run_dir == run_dir:
        return _zone_store

    print(f"  Инициализация ZoneStore из {run_dir}...")
    zs = ZoneStore()

    schemas_path = f"{run_dir}/03_schemas.json"
    if Path(schemas_path).exists():
        with open(schemas_path) as f:
            raw = json.load(f)
        schemas = {int(k): v for k, v in raw.items()} if isinstance(raw, dict) else {s["page_id"]: s for s in raw}
        zs.add_zones_from_schemas(schemas)

    _zone_store = zs
    _cached_run_dir = run_dir
    return zs


def _init_cross_page_linker(run_dir: str) -> CrossPageLinker:
    """Инициализирует CrossPageLinker."""
    global _cross_page_linker
    if _cross_page_linker is not None and _cached_run_dir == run_dir:
        return _cross_page_linker

    zs = _init_zone_store(run_dir)
    cpl = CrossPageLinker()

    # Пробуем загрузить сохранённый граф
    graph_path = f"{run_dir}/09_cross_page_graph.json"
    if Path(graph_path).exists():
        with open(graph_path) as f:
            data = json.load(f)
            cpl.edges = data.get("edges", [])
            print(f"  CrossPageLinker: loaded {len(cpl.edges)} edges from cache")
    else:
        cpl.find_connections(zs, max_pairs=50)
        with open(graph_path, "w") as f:
            json.dump(cpl.to_dict(), f, ensure_ascii=False, indent=2)

    _cross_page_linker = cpl
    return cpl


def _build_context_dynamic(question: str, data: dict, run_dir: str) -> str:
    """Динамическая сборка контекста: ZoneStore + CrossPageLinker + онтология."""
    import re
    parts = []
    zs = _init_zone_store(run_dir)

    # 0. Извлекаем номера страниц из вопроса
    page_nums = set()
    for m in re.finditer(r'(?:стр|страниц|page|p)[а-я]*\s*(\d+)', question.lower()):
        page_nums.add(int(m.group(1)))
    # Захватываем числа после "и" или запятой в контексте страниц
    for m in re.finditer(r'(?:стр|страниц|page|p)[а-я]*\s*\d+[\s,]*и\s*(\d+)', question.lower()):
        page_nums.add(int(m.group(1)))
    # Просто числа 1-99 в контексте вопроса о страницах
    if page_nums and any(w in question.lower() for w in ['стр', 'страниц', 'page']):
        for m in re.finditer(r'\b(\d{1,2})\b', question):
            n = int(m.group(1))
            if 1 <= n <= 99:
                page_nums.add(n)

    # 1. Векторный поиск по зонам
    zone_context = zs.get_context_for_query(question, max_zones=15, max_chars=6000)

    # 2. Добавляем явно запрошенные страницы
    if page_nums:
        schemas = data.get("schemas", {})
        explicit_parts = []
        for pn in sorted(page_nums):
            if pn in schemas:
                s = schemas[pn]
                form = s.get("form", "discursive")
                content = ""

                # Для mixed: используем zone_schemas вместо overall_structure
                if form == "mixed" and s.get("zone_schemas"):
                    for zform, zschema in s["zone_schemas"].items():
                        if isinstance(zschema, dict):
                            zcontent = zschema.get("conclusion", zschema.get("page_title", ""))
                            if zcontent:
                                content += f"\n[{zform}] {zcontent[:1000]}"
                if not content:
                    content = zs._zone_to_text(s, form)

                if content:
                    explicit_parts.append(f"### стр. {pn} [{form}] (ЯВНО ЗАПРОШЕНА)")
                    explicit_parts.append(content[:1500])
                    explicit_parts.append("")
        if explicit_parts:
            zone_context = "## ЯВНО ЗАПРОШЕННЫЕ СТРАНИЦЫ\n" + "\n".join(explicit_parts) + "\n" + zone_context

    parts.append(zone_context)

    # 2. Executive summary из рекомендаций
    recs = data.get("recommendations", {})
    exec_summary = recs.get("executive_summary", "")
    if exec_summary:
        parts.append(f"\n## EXECUTIVE SUMMARY\n{exec_summary[:500]}")

    # 3. Топ-рекомендации
    top = recs.get("top_recommendations", [])
    if top:
        parts.append("\n## КЛЮЧЕВЫЕ РЕКОМЕНДАЦИИ")
        for r in top[:10]:
            parts.append(f"- p{r.get('page', '?')} [{r.get('urgency', '?')}]: {r.get('action', '')[:150]}")

    # 4. Стратегические риски и возможности
    risks = recs.get("strategic_risks", [])
    if risks:
        parts.append("\n## СТРАТЕГИЧЕСКИЕ РИСКИ")
        for r in risks[:5]:
            parts.append(f"- {r[:200]}")

    opps = recs.get("strategic_opportunities", [])
    if opps:
        parts.append("\n## СТРАТЕГИЧЕСКИЕ ВОЗМОЖНОСТИ")
        for o in opps[:5]:
            parts.append(f"- {o[:200]}")

    # 5. Онтология (если есть)
    ont_path = f"{run_dir}/04_ontologies.json"
    if Path(ont_path).exists():
        with open(ont_path) as f:
            ontologies = json.load(f)
        parts.append(f"\n## ОНТОЛОГИЯ ДОКУМЕНТА ({len(ontologies)} стр.)")
        for o in ontologies[:15]:
            model = o.get("model", "")
            if model:
                parts.append(f"- p{o['page_id']}: {model[:150]}")

    # 6. Кросс-страничные связи (для вопросов о связях)
    if any(w in question.lower() for w in ["связ", "завис", "отношен", "между"]):
        cpl = _init_cross_page_linker(run_dir)
        if cpl.edges:
            parts.append(f"\n## КРОСС-СТРАНИЧНЫЕ СВЯЗИ ({len(cpl.edges)} рёбер)")
            for e in cpl.edges[:10]:
                parts.append(f"- p{e['source_page']} --[{e['relation_type']}]--> p{e['target_page']} "
                           f"({e.get('explanation', '')[:100]})")

    return "\n".join(parts)


ROUTE_PROMPT = """[РОЛЬ] Маршрутизатор C-level вопросов
[ПРЕДМЕТ] Вопрос руководителя + контекст документа
[ЗАДАЧА] Определи тип вопроса и выбери режим ответа
[ПРАВИЛА]
Типы вопросов:
- "risks" — вопрос о рисках и угрозах
- "opportunities" — вопрос о возможностях
- "why" — вопрос «почему» (требует provenance)
- "page" — вопрос о конкретной странице
- "what_if" — гипотетический вопрос (требует HTR)
- "connections" — вопрос о связях между разделами
- "general" — общий вопрос

Режимы ответа:
- "direct" — прямой ответ из данных
- "provenance" — с трассировкой источника
- "multi_position" — с advocate/skeptic/synthesizer
- "doubt_first" — сначала проверить confidence

Формат: JSON
{{
  "question_type": "risks|opportunities|why|page|what_if|connections|general",
  "answer_mode": "direct|provenance|multi_position|doubt_first",
  "relevant_pages": [N, ...],
  "confidence": "HIGH|MEDIUM|LOW"
}}

## ВОПРОС
{question}

## КОНТЕКСТ
{context}"""


ANSWER_PROMPT = """[РОЛЬ] C-level аналитик (AI Canvas)
[ПРЕДМЕТ] Ответ на вопрос руководителя на основе вычислительного графа документа
[ЗАДАЧА] Дай структурированный ответ
[ПРАВИЛА]
1. Отвечай ТОЛЬКО на основе предоставленного контекста
2. Для каждого утверждения указывай источник (страницу)
3. Если данных недостаточно — честно скажи
4. Для стратегических вопросов — дай multi-position view (advocate/skeptic/synthesizer)
5. Укажи confidence ответа
[ОГРАНИЧЕНИЕ] Не выдумывай. Только контекст. Если нет данных — скажи «недостаточно данных».

Формат: JSON
{{
  "answer": "string — краткий ответ (1-2 предложения)",
  "details": ["string — детализация"],
  "sources": [{{"page": N, "form": "string", "evidence": "string"}}],
  "advocate_view": "string or null",
  "skeptic_view": "string or null",
  "synthesizer_view": "string or null",
  "unknown_zones": ["string — что мы не знаем"],
  "confidence": "HIGH|MEDIUM|LOW",
  "mode": "direct|provenance|multi_position"
}}

## ВОПРОС
{question}

## КОНТЕКСТ ДОКУМЕНТА
{context}"""


def ask(question: str, run_dir: str | None = None) -> dict:
    """Задаёт вопрос оркестратору и возвращает структурированный ответ."""
    if run_dir is None:
        run_dir = _find_latest_run()

    t0 = time.time()
    data = _load_data(run_dir)

    if not data.get("recommendations") and not data.get("schemas"):
        return {"answer": "Нет данных прогона. Запустите pipeline.", "confidence": "LOW", "mode": "direct"}

    # Строим контекст (динамический: ZoneStore + CrossPageLinker)
    context = _build_context_dynamic(question, data, run_dir)

    # Маршрутизация
    route_prompt = ROUTE_PROMPT.format(question=question, context=context[:3000])
    route_result = _parse_json(_call_ollama(route_prompt, max_tokens=512))
    question_type = route_result.get("question_type", "general")
    answer_mode = route_result.get("answer_mode", "direct")

    # Генерируем ответ
    answer_prompt = ANSWER_PROMPT.format(question=question, context=context[:5000])
    answer_result = _parse_json(_call_ollama(answer_prompt, max_tokens=2048))

    # Doubt Gate
    dg = MetaCognitiveReflector(threshold=0.65)
    doubt_confidence = answer_result.get("confidence", "MEDIUM")
    doubt_map = {"HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.2}
    conf_value = doubt_map.get(doubt_confidence, 0.5)
    blocked = conf_value < 0.65

    # Dialogue (для strategic вопросов)
    dialogue = None
    if question_type in ("risks", "opportunities", "what_if", "general"):
        dm = DialogueOrchestrator()
        try:
            # Строим минимальную онтологию из контекста
            ont = {
                "entities": [{"name": r.get("action", "")[:60], "type": "Рекомендация", "role": ""}
                            for r in data.get("recommendations", {}).get("top_recommendations", [])[:3]],
                "relations": [],
                "model": data.get("recommendations", {}).get("executive_summary", "")[:200],
            }
            refl = {"recommended_action": answer_result.get("answer", question)[:200], "urgency": "MEDIUM"}
            state = dm.start_dialogue("c_level", ont, refl)
            dialogue = {
                "positions": [{"role": p.role, "statement": p.statement} for p in state.positions],
                "turns": len(state.history),
            }
        except Exception:
            dialogue = None

    elapsed = time.time() - t0

    return {
        "question": question,
        "question_type": question_type,
        "answer_mode": answer_mode,
        "answer": answer_result.get("answer", ""),
        "details": answer_result.get("details", []),
        "sources": answer_result.get("sources", []),
        "advocate_view": answer_result.get("advocate_view"),
        "skeptic_view": answer_result.get("skeptic_view"),
        "synthesizer_view": answer_result.get("synthesizer_view"),
        "unknown_zones": answer_result.get("unknown_zones", []),
        "confidence": doubt_confidence,
        "doubt_blocked": blocked,
        "dialogue": dialogue,
        "mode": answer_result.get("mode", answer_mode),
        "elapsed_s": round(elapsed, 1),
        "run_dir": run_dir,
    }


def format_answer(result: dict) -> str:
    """Форматирует ответ для вывода в терминал."""
    lines = []

    # Confidence + urgency
    conf = result["confidence"]
    conf_icon = "🟢" if conf == "HIGH" else "🟡" if conf == "MEDIUM" else "🔴"
    blocked = "🚫 BLOCKED — " if result["doubt_blocked"] else ""
    lines.append(f"\n{conf_icon} {blocked}Confidence: {conf} | Mode: {result['mode']} | {result['elapsed_s']}s")
    lines.append("=" * 60)

    # Answer
    lines.append(f"\n{result['answer']}")

    # Details
    if result["details"]:
        lines.append("\n📋 Детали:")
        for d in result["details"]:
            lines.append(f"  • {d}")

    # Sources
    if result["sources"]:
        lines.append("\n📄 Источники:")
        for s in result["sources"]:
            lines.append(f"  стр. {s['page']} [{s.get('form', '?')}]: {s.get('evidence', '')[:120]}")

    # Multi-position
    if result["advocate_view"]:
        lines.append(f"\n[ADVOCATE] {result['advocate_view']}")
    if result["skeptic_view"]:
        lines.append(f"\n[SKEPTIC] {result['skeptic_view']}")
    if result["synthesizer_view"]:
        lines.append(f"\n[SYNTHESIZER] {result['synthesizer_view']}")

    # Dialogue
    if result.get("dialogue"):
        d = result["dialogue"]
        lines.append(f"\n💬 Диалог ({d['turns']} ходов, {len(d['positions'])} позиций):")
        for p in d["positions"]:
            lines.append(f"  [{p['role'].upper()}] {p['statement'][:120]}")

    # Unknown zones
    if result["unknown_zones"]:
        lines.append("\n⚠️ Зоны неизвестности:")
        for z in result["unknown_zones"]:
            lines.append(f"  • {z}")

    lines.append(f"\n📁 Данные: {result['run_dir']}")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="C-level Q&A оркестратор")
    parser.add_argument("question", nargs="?", help="Вопрос на естественном языке")
    parser.add_argument("--run", help="Путь к run-директории", default=None)
    parser.add_argument("--json", action="store_true", help="Вывод в JSON")
    args = parser.parse_args()

    if not args.question:
        # Интерактивный режим
        print("AI Canvas — C-level Q&A оркестратор")
        print("Введите вопрос (или 'exit' для выхода):")
        while True:
            try:
                q = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in ("exit", "quit", "q"):
                break
            if not q:
                continue
            result = ask(q, args.run)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(format_answer(result))
    else:
        result = ask(args.question, args.run)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_answer(result))


if __name__ == "__main__":
    main()