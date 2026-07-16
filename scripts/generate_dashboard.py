#!/usr/bin/env python3
"""Генератор дашборда из схем и классификации.

Запуск:
  python3 scripts/generate_dashboard.py output/run_2026-07-15_1107/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _best_zone_schema(schema: dict) -> dict | None:
    """Для mixed-страниц: находит самую информативную zone_schema."""
    zone_schemas = schema.get("zone_schemas", {})
    if not zone_schemas:
        return None
    # Приоритет: topology > spatial > matrix > enumeration > discursive
    priority = ["topology", "spatial", "matrix", "dynamics", "hierarchy", "enumeration", "discursive"]
    for form in priority:
        if form in zone_schemas:
            zs = zone_schemas[form]
            if isinstance(zs, dict):
                return zs
    # Любая доступная
    first = next(iter(zone_schemas.values()))
    return first if isinstance(first, dict) else None


def _extract_title(schema: dict) -> str:
    """Извлекает заголовок из схемы."""
    # Для mixed: ищем в zone_schemas
    if schema.get("form") == "mixed":
        best = _best_zone_schema(schema)
        if best:
            for key in ("page_title", "title"):
                val = best.get(key, "")
                if val and isinstance(val, str) and len(val) > 5:
                    return val[:120]

    for key in ("page_title", "title", "overall_structure"):
        val = schema.get(key, "")
        if val and isinstance(val, str) and len(val) > 5:
            return val[:120]
    return "(без заголовка)"


def _extract_summary(schema: dict) -> str:
    """Извлекает краткое содержание."""
    # Для mixed: ищем в zone_schemas
    if schema.get("form") == "mixed":
        best = _best_zone_schema(schema)
        if best:
            concl = best.get("conclusion", "")
            if concl and isinstance(concl, str) and len(concl) > 10:
                return concl[:200]
            items = best.get("items", [])
            if items:
                return "; ".join([i[:80] for i in items[:3] if isinstance(i, str)])[:200]
            # Для topology: перечисляем sets
            sets = best.get("sets", [])
            if sets:
                names = [s.get("name", "") for s in sets[:3] if s.get("name")]
                if names:
                    return "Сравнение: " + " vs ".join(names)

    # Стандартные поля
    concl = schema.get("conclusion", "")
    if concl and isinstance(concl, str) and len(concl) > 10:
        return concl[:200]

    theses = schema.get("key_theses", [])
    if theses:
        return "; ".join(theses[:3])[:200]

    model = schema.get("model", "")
    if model and isinstance(model, str):
        return model[:200]

    ft = schema.get("full_text", "")
    if ft:
        return ft[:200]

    return "(нет данных)"


def _extract_entities(schema: dict) -> list[str]:
    """Извлекает ключевые сущности."""
    entities = []

    # Для mixed: ищем в zone_schemas
    if schema.get("form") == "mixed":
        best = _best_zone_schema(schema)
        if best:
            # Из sets (topology)
            for s in best.get("sets", []):
                entities.append(s.get("name", "")[:60])
            # Из items (enumeration)
            for item in best.get("items", [])[:3]:
                if isinstance(item, str):
                    entities.append(item[:60])
            # Из regions (spatial)
            for r in best.get("regions", [])[:5]:
                name = r.get("name", "")
                if name:
                    entities.append(name[:60])
            # Метрики
            for m in best.get("all_metrics", [])[:5]:
                label = m.get("label", "")
                if label:
                    entities.append(label[:60])

    if entities:
        return [e for e in entities if e][:8]

    # Стандартные поля
    for s in schema.get("sets", []):
        entities.append(s.get("name", "")[:60])

    for l in schema.get("levels", []):
        entities.append(l.get("label", "")[:60])

    for t in schema.get("key_terms", []):
        if isinstance(t, str):
            entities.append(t[:60])

    for item in schema.get("items", [])[:3]:
        if isinstance(item, str):
            entities.append(item[:60])
        elif isinstance(item, dict):
            entities.append(str(item.get("label", item.get("name", "")))[:60])

    for z in schema.get("zones", [])[:5]:
        desc = z.get("description", "")
        if desc:
            entities.append(f"[{z.get('form', '?')}] {desc}"[:80])

    return [e for e in entities if e][:8]


def generate_html(run_dir: str) -> str:
    """Генерирует HTML дашборда."""
    # Загружаем данные
    with open(f"{run_dir}/01_semiotic_classification.json") as f:
        classification = json.load(f)

    with open(f"{run_dir}/03_schemas.json") as f:
        schemas_raw = json.load(f)
    if isinstance(schemas_raw, dict):
        schemas = {int(k): v for k, v in schemas_raw.items()}
    else:
        schemas = {s["page_id"]: s for s in schemas_raw}

    # Загружаем рекомендации (07_recommendations.json)
    annotations_by_page = {}
    top_recs = []
    try:
        with open(f"{run_dir}/07_recommendations.json") as f:
            recs_data = json.load(f)
        for pa in recs_data.get("page_annotations", []):
            annotations_by_page[pa["page"]] = pa
        top_recs = recs_data.get("top_recommendations", [])
    except (FileNotFoundError, KeyError):
        pass

    # Пробуем загрузить онтологии (если есть)
    ontologies = {}
    try:
        with open(f"{run_dir}/04_ontologies.json") as f:
            ont_list = json.load(f)
        ontologies = {o["page_id"]: o for o in ont_list}
    except (FileNotFoundError, KeyError):
        pass

    # Строим страницы дашборда
    dashboard_pages = []
    for p in classification["pages"]:
        pid = p["page_id"]
        form = p["primary_form"]
        schema = schemas.get(pid, {})
        title = _extract_title(schema)
        summary = _extract_summary(schema)
        entities = _extract_entities(schema)

        # Берём аннотацию из рекомендаций
        ann = annotations_by_page.get(pid, {})
        action = ann.get("annotation", summary[:150])
        urgency = ann.get("urgency", "LOW")
        confidence = p.get("confidence", "MEDIUM")

        # Проверяем, есть ли top recommendation для этой страницы
        for rec in top_recs:
            if rec.get("page") == pid:
                action = rec.get("action", action)
                urgency = rec.get("urgency", urgency)
                break

        ont = ontologies.get(pid, {})
        ont_entities = [
            {"name": e.get("name", ""), "type": e.get("type", ""), "role": e.get("role", "")}
            for e in ont.get("entities", [])[:5]
        ]
        ont_relations = [
            {"from": r.get("from", ""), "to": r.get("to", ""), "type": r.get("type", "")}
            for r in ont.get("relations", [])[:5]
        ]

        dashboard_pages.append({
            "page": pid,
            "form": form,
            "title": title,
            "summary": summary,
            "entities": entities,
            "action": action,
            "urgency": urgency,
            "confidence": confidence,
            "rationale": p.get("rationale", "")[:100],
            "ont_entities": ont_entities,
            "ont_relations": ont_relations,
        })

    # Формируем HTML
    dist = classification["stats"]["form_distribution"]
    total = classification["stats"]["total_pages"]
    high = sum(1 for dp in dashboard_pages if dp["urgency"] == "HIGH")
    medium = sum(1 for dp in dashboard_pages if dp["urgency"] == "MEDIUM")

    pages_json = json.dumps(dashboard_pages, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Canvas — Дашборд: ИАфр РАН ({total} стр.)</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; display:flex; height:100vh; }}
.panel {{ padding:24px; overflow-y:auto; }}
.left {{ width:55%; border-right:1px solid #1e293b; }}
.right {{ width:45%; display:flex; flex-direction:column; }}
h1 {{ font-size:20px; margin-bottom:4px; }}
h2 {{ font-size:14px; color:#94a3b8; margin-bottom:16px; }}
.metric {{ background:#1e293b; border-radius:8px; padding:16px; margin-bottom:10px; cursor:pointer; transition:background 0.2s; }}
.metric:hover {{ background:#334155; }}
.metric .page {{ color:#64748b; font-size:12px; }}
.metric .form {{ display:inline-block; background:#334155; padding:2px 8px; border-radius:4px; font-size:11px; margin-left:8px; }}
.metric .title {{ font-size:14px; font-weight:600; margin-top:6px; line-height:1.4; }}
.metric .summary {{ font-size:13px; color:#94a3b8; margin-top:4px; line-height:1.4; }}
.metric .entities {{ display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }}
.metric .entity {{ background:#0f172a; padding:2px 8px; border-radius:4px; font-size:11px; color:#94a3b8; }}
.metric .action {{ margin-top:8px; font-size:14px; line-height:1.5; color:#f8fafc; }}
.metric .urgency {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; margin-top:6px; }}
.urgency.HIGH {{ background:#7f1d1d; color:#fca5a5; }}
.urgency.MEDIUM {{ background:#78350f; color:#fcd34d; }}
.urgency.LOW {{ background:#14532d; color:#86efac; }}
.stats {{ display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; }}
.stat {{ background:#1e293b; border-radius:8px; padding:16px; flex:1; text-align:center; min-width:80px; }}
.stat .value {{ font-size:28px; font-weight:bold; }}
.stat .label {{ font-size:12px; color:#64748b; margin-top:4px; }}
.tabs {{ display:flex; gap:4px; margin-bottom:16px; flex-wrap:wrap; }}
.tab {{ background:#1e293b; border:none; padding:8px 16px; border-radius:6px; color:#94a3b8; cursor:pointer; font-size:13px; }}
.tab.active {{ background:#2563eb; color:white; }}
.chat {{ flex:1; display:flex; flex-direction:column; }}
.chat-messages {{ flex:1; overflow-y:auto; padding:16px; }}
.chat-msg {{ margin-bottom:12px; max-width:85%; }}
.chat-msg.user {{ margin-left:auto; }}
.chat-msg.user .bubble {{ background:#2563eb; }}
.chat-msg.assistant .bubble {{ background:#1e293b; }}
.bubble {{ padding:12px 16px; border-radius:12px; font-size:14px; line-height:1.5; }}
.chat-input {{ display:flex; padding:16px; border-top:1px solid #1e293b; }}
.chat-input input {{ flex:1; background:#1e293b; border:none; padding:12px; border-radius:8px; color:#e2e8f0; font-size:14px; }}
.chat-input button {{ background:#2563eb; border:none; padding:12px 20px; border-radius:8px; color:white; margin-left:8px; cursor:pointer; font-size:14px; }}
.chat-input button:disabled {{ opacity:0.5; }}
.loading {{ color:#64748b; font-style:italic; }}
.detail-panel {{ display:none; position:fixed; top:10%; left:10%; width:80%; height:80%; background:#1e293b; border-radius:12px; padding:24px; overflow-y:auto; z-index:100; box-shadow:0 20px 60px rgba(0,0,0,0.5); }}
.detail-panel.active {{ display:block; }}
.detail-panel .close {{ float:right; background:none; border:none; color:#94a3b8; font-size:24px; cursor:pointer; }}
.overlay {{ display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:99; }}
.overlay.active {{ display:block; }}
</style>
</head>
<body>

<div class="overlay" id="overlay" onclick="closeDetail()"></div>
<div class="detail-panel" id="detail"></div>

<div class="panel left">
    <h1>📊 ИАфр РАН — Стратегия продвижения деловых интересов</h1>
    <h2>{total} страниц → полный вычислительный граф</h2>

    <div class="stats">
        <div class="stat"><div class="value">{total}</div><div class="label">Страниц</div></div>
        <div class="stat"><div class="value">{high}</div><div class="label">HIGH urgency</div></div>
        <div class="stat"><div class="value">{medium}</div><div class="label">MED urgency</div></div>
        <div class="stat"><div class="value">{len(dist)}</div><div class="label">Форм</div></div>
    </div>

    <div class="tabs" id="tabs">
        <button class="tab active" onclick="filterBy('all', this)">Все ({total})</button>
        <button class="tab" onclick="filterBy('HIGH', this)">🔴 HIGH ({high})</button>
        <button class="tab" onclick="filterBy('MEDIUM', this)">🟡 MEDIUM ({medium})</button>
"""
    for form, count in sorted(dist.items(), key=lambda x: -x[1]):
        html += f'        <button class="tab" onclick="filterBy(\'{form}\', this)">{form} ({count})</button>\n'

    html += """    </div>

    <div id="dashboard"></div>
</div>

<div class="panel right">
    <div class="chat" id="chat">
        <div class="chat-messages" id="messages">
            <div class="chat-msg assistant">
                <div class="bubble">
                    Я — AI-ассистент, опирающийся на вычислительный граф документа.<br>
                    Спросите о страницах, рисках, рекомендациях или связях между разделами.
                </div>
            </div>
        </div>
        <div class="chat-input">
            <input id="query" placeholder="Спросите о документе..." onkeydown="if(event.key==='Enter')ask()">
            <button id="sendBtn" onclick="ask()">→</button>
        </div>
    </div>
</div>

<script>
const DATA = """ + pages_json + """;

const FORM_LABELS = {
    'discursive': '📝 Текст', 'topology': '🔵 Топология', 'matrix': '📊 Матрица',
    'hierarchy': '🔺 Иерархия', 'spatial': '🗺 Карта', 'enumeration': '📋 Список',
    'dynamics': '📈 Динамика', 'mixed': '🔀 Mixed', 'empty': '⬜ Пустая'
};

let currentFilter = 'all';

function filterBy(filter, el) {
    currentFilter = filter;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    if (el) el.classList.add('active');
    renderDashboard();
}

function renderDashboard() {
    const el = document.getElementById('dashboard');
    el.innerHTML = '';
    DATA.forEach(p => {
        if (currentFilter !== 'all' && currentFilter !== p.urgency && currentFilter !== p.form) return;
        const formLabel = FORM_LABELS[p.form] || p.form;
        const entities = p.entities.slice(0, 5).map(e => `<span class="entity">${e}</span>`).join('');
        el.innerHTML += `
            <div class="metric" onclick="showDetail(${p.page})">
                <span class="page">Стр. ${p.page}</span>
                <span class="form">${formLabel}</span>
                <span class="urgency ${p.urgency}">${p.urgency}</span>
                <div class="title">${p.title}</div>
                <div class="summary">${p.summary}</div>
                ${entities ? '<div class="entities">' + entities + '</div>' : ''}
                ${p.action && p.action !== p.summary ? '<div class="action">💡 ' + p.action + '</div>' : ''}
            </div>`;
    });
    if (el.innerHTML === '') el.innerHTML = '<div style="padding:24px;color:#64748b;">Нет страниц по фильтру</div>';
}

function showDetail(pageId) {
    const p = DATA.find(d => d.page === pageId);
    if (!p) return;
    const ontEnts = p.ont_entities.map(e => `<tr><td>${e.name}</td><td>${e.type}</td><td>${e.role}</td></tr>`).join('');
    const ontRels = p.ont_relations.map(r => `<tr><td>${r.from}</td><td>→ ${r.type} →</td><td>${r.to}</td></tr>`).join('');
    document.getElementById('detail').innerHTML = `
        <button class="close" onclick="closeDetail()">&times;</button>
        <h2>Стр. ${p.page} — ${FORM_LABELS[p.form] || p.form}</h2>
        <p style="color:#94a3b8;margin:8px 0">${p.rationale}</p>
        <h3 style="margin-top:16px">${p.title}</h3>
        <p style="color:#94a3b8">${p.summary}</p>
        ${p.action ? '<p style="margin-top:12px;font-size:16px"><span class="urgency ' + p.urgency + '">' + p.urgency + '</span> 💡 ' + p.action + '</p>' : ''}
        ${ontEnts ? '<h3 style="margin-top:16px">Онтология</h3><table style="width:100%;border-collapse:collapse"><tr style="color:#64748b"><th>Сущность</th><th>Тип</th><th>Роль</th></tr>' + ontEnts + '</table>' : ''}
        ${ontRels ? '<h3 style="margin-top:16px">Отношения</h3><table style="width:100%;border-collapse:collapse"><tr style="color:#64748b"><th>От</th><th>Тип</th><th>К</th></tr>' + ontRels + '</table>' : ''}
    `;
    document.getElementById('detail').classList.add('active');
    document.getElementById('overlay').classList.add('active');
}

function closeDetail() {
    document.getElementById('detail').classList.remove('active');
    document.getElementById('overlay').classList.remove('active');
}

renderDashboard();

// Чат
async function ask() {
    const input = document.getElementById('query');
    const q = input.value.trim();
    if (!q) return;
    input.value = '';

    const msgs = document.getElementById('messages');
    msgs.innerHTML += `<div class="chat-msg user"><div class="bubble">${q}</div></div>`;
    msgs.innerHTML += `<div class="chat-msg assistant"><div class="bubble loading">Анализирую граф...</div></div>`;
    msgs.scrollTop = msgs.scrollHeight;

    const btn = document.getElementById('sendBtn');
    btn.disabled = true;

    const graphContext = JSON.stringify(DATA, null, 2);
    const prompt = `[РОЛЬ] Аналитик графа знаний
[ПРЕДМЕТ] Документ «Стратегия ИАфр РАН» — """ + str(total) + """ страниц
[ПРАВИЛА] Отвечай ТОЛЬКО на основе данных графа. Если данных недостаточно — честно скажи.
[ОГРАНИЧЕНИЕ] Не выдумывай. Только граф.

## ГРАФ ДОКУМЕНТА
${graphContext}

## ВОПРОС
${q}`;

    try {
        const resp = await fetch('http://localhost:11434/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                model: 'qwen3.6:35b',
                messages: [{role: 'user', content: prompt}],
                max_tokens: 1024,
                temperature: 0.1,
                stream: false,
            }),
        });
        const data = await resp.json();
        const answer = data.message.content;

        const bubbles = msgs.querySelectorAll('.bubble');
        bubbles[bubbles.length - 1].textContent = answer;
        bubbles[bubbles.length - 1].classList.remove('loading');
    } catch(e) {
        const bubbles = msgs.querySelectorAll('.bubble');
        bubbles[bubbles.length - 1].textContent = 'Ошибка: ' + e.message;
        bubbles[bubbles.length - 1].classList.remove('loading');
    }

    btn.disabled = false;
    msgs.scrollTop = msgs.scrollHeight;
}
</script>
</body>
</html>"""

    return html


def main():
    if len(sys.argv) < 2:
        runs = sorted(Path("output").glob("run_*"))
        if not runs:
            print("Нет run-директорий")
            sys.exit(1)
        run_dir = str(runs[-1])
    else:
        run_dir = sys.argv[1]

    html = generate_html(run_dir)
    out_path = f"{run_dir}/08_dashboard.html"
    with open(out_path, "w") as f:
        f.write(html)

    print(f"Дашборд сохранён: {out_path}")
    print(f"  Размер: {len(html)} байт")


if __name__ == "__main__":
    main()