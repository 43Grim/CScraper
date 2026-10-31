"""Self-contained HTML outputs: the portfolio dashboard and one page per rubric.

Both open straight from disk (no server, no internet) and link to the
downloaded files with relative paths, so the folder or ZIP can be moved.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

_CSS = """
:root{--bg:#f6f6f7;--card:#fff;--ink:#18181b;--muted:#71717a;--line:#e4e4e7;--accent:#2563eb;--accent-soft:#eff6ff;--hit:#dcfce7;--hit-ink:#14532d;--chip:#f4f4f5}
@media (prefers-color-scheme:dark){:root{--bg:#1e1e20;--card:#26262a;--ink:#e4e4e7;--muted:#a1a1aa;--line:#3a3a40;--accent:#60a5fa;--accent-soft:#1e293b;--hit:#1f3b2b;--hit-ink:#bbf7d0;--chip:#2c2c31}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
a{color:var(--accent)}header{padding:24px 16px 8px;max-width:1100px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted)}main{max-width:1100px;margin:0 auto;padding:0 16px 48px}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 14px}
.stat b{display:block;font-size:20px}.bar{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 18px;position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:2}
select,input[type=search]{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
input[type=search]{flex:1;min-width:180px}@media (prefers-color-scheme:dark){.st-graded,.st-submitted{color:#4ade80;border-color:#166534}.st-overdue{color:#f87171;border-color:#7f1d1d}}h2{font-size:16px;margin:26px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
details.task{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0}
details.task>summary{list-style:none;cursor:pointer;padding:10px 14px;display:grid;grid-template-columns:1fr auto;gap:4px 12px;align-items:center}
details.task>summary::-webkit-details-marker{display:none}.tname{font-weight:600}.meta{color:var(--muted);font-size:12px}
.grade{font-weight:600;color:var(--accent);text-align:right;white-space:nowrap}.chip{display:inline-block;font-size:11px;padding:1px 8px;border-radius:99px;background:var(--chip);margin-right:6px;color:#fff}
.body{padding:0 14px 14px;border-top:1px solid var(--line)}h3{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:16px 0 6px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}
th{background:var(--chip);font-weight:600}.pre{white-space:pre-wrap}.gtable td:first-child{width:32%;font-weight:600}
.rub td.hit{background:var(--hit);color:var(--hit-ink)}.rub ul{margin:0;padding-left:16px}.files li{margin:2px 0}.err{color:#d92d20}
.scroll{overflow-x:auto}.st{font-size:11px;padding:1px 7px;border-radius:99px;border:1px solid var(--line);color:var(--muted);white-space:nowrap;font-weight:500}
.st-graded,.st-submitted{color:#15803d;border-color:#86efac}.st-overdue{color:#dc2626;border-color:#fca5a5}.st-due-soon{color:var(--accent);border-color:var(--accent)}.empty{color:var(--muted);font-style:italic}
"""

_JS = r"""
const DATA = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const el = (tag, props = {}, ...kids) => { const e = document.createElement(tag); Object.assign(e, props); kids.flat(Infinity).forEach(k => k != null && e.append(k)); return e; };
const fmtDate = s => { if (!s) return ''; const d = new Date(s); return isNaN(d) ? s : d.toLocaleDateString(undefined, {day:'numeric', month:'short', year:'numeric'}); };
const NOW = new Date();
function status(t) {
  if (t.grades.some(g => g.display) || t.rubrics.some(r => r.criteria.some(c => c.awarded))) return 'Graded';
  if (t.submissions.length || t.submittedTimestamp) return 'Submitted';
  if (!t.dueDate) return 'No due date';
  const due = new Date(t.dueDate);
  if (due < NOW) return 'Overdue';
  return (due - NOW) / 864e5 <= 7 ? 'Due soon' : 'Pending';
}
const GROUPS = {'To do': ['Overdue', 'Due soon', 'Pending', 'No due date'], 'Completed': ['Graded', 'Submitted']};
const HAS = {rubric: t => t.rubrics.length, comment: t => t.grades.some(g => g.isComment && g.display), submission: t => t.submissions.length,
  files: t => t.attachments.length + t.submissions.length + t.teacherResponses.length};
const years = [...new Set(DATA.tasks.map(t => t.year))];
const yearSel = $('#year'), subjSel = $('#subject');
years.forEach(y => yearSel.append(el('option', {value: y, textContent: y})));
if (years.length) yearSel.value = years[years.length - 1];
function refreshSubjects() {
  const keep = subjSel.value;
  subjSel.replaceChildren(el('option', {value: '', textContent: 'All subjects'}));
  [...new Set(DATA.tasks.filter(t => !yearSel.value || t.year === yearSel.value).map(t => t.subject))].sort()
    .forEach(s => subjSel.append(el('option', {value: s, textContent: s})));
  subjSel.value = [...subjSel.options].some(o => o.value === keep) ? keep : '';
}
function fileList(title, files) {
  if (!files.length) return null;
  return [el('h3', {textContent: title}), el('ul', {className: 'files'}, files.map(f => el('li', {},
    f.path ? el('a', {href: f.path, textContent: f.fileName || f.name}) : f.link ? el('a', {href: f.link, textContent: f.link, target: '_blank', rel: 'noopener'}) : (f.fileName || f.name),
    (f.submitted || f.uploaded) ? el('span', {className: 'meta', textContent: '  ' + fmtDate(f.submitted || f.uploaded)}) : null,
    f.error ? el('span', {className: 'err', textContent: '  (download failed: ' + f.error + ')'}) : null)))];
}
function rubricTable(r) {
  return el('div', {className: 'scroll'}, el('table', {className: 'rub'},
    el('tr', {}, el('th', {textContent: 'Criteria'}), r.columns.map(c => el('th', {textContent: c}))),
    r.criteria.map(c => el('tr', {}, el('td', {}, el('b', {textContent: c.criterion || ''}), c.description ? el('div', {className: 'pre meta', textContent: c.description}) : null),
      r.columns.map(col => { const cell = c.cells.find(x => x.column === col);
        return el('td', {className: cell && cell.awarded ? 'hit' : ''}, cell ? el('ul', {}, cell.points.filter(Boolean).map(p => el('li', {textContent: p}))) : null); })))));
}
function taskCard(t) {
  const grades = t.grades.filter(g => g.display !== '');
  const meta = [t.category, t.className, t.dueDate ? 'Due ' + fmtDate(t.dueDate) : null, t.submittedTimestamp ? 'Submitted ' + fmtDate(t.submittedTimestamp) : null].filter(Boolean).join('  ·  ');
  const body = el('div', {className: 'body'},
    el('h3', {textContent: 'Grades & feedback'}),
    grades.length ? el('table', {className: 'gtable'}, grades.map(g => el('tr', {}, el('td', {textContent: g.item || ''}), el('td', {className: g.isComment ? 'pre' : '', textContent: g.display}))))
                  : el('div', {className: 'empty', textContent: 'No results released.'}),
    t.rubrics.map(r => [el('h3', {}, 'Rubric: ' + (r.name || ''), r.path ? ['  ', el('a', {href: r.path, textContent: 'open / print'})] : null), rubricTable(r)]),
    fileList('Attachments', t.attachments), fileList('Submissions', t.submissions), fileList('Teacher responses', t.teacherResponses),
    t.descriptionText ? [el('h3', {textContent: 'Task description'}), el('div', {className: 'pre', textContent: t.descriptionText})] : null,
    el('p', {className: 'meta'}, el('a', {href: t.folder + '/task.json', textContent: 'task.json'}), '  ·  ', el('a', {href: t.folder, textContent: 'folder'})));
  const st = status(t);
  const stChip = el('span', {className: 'st st-' + st.toLowerCase().replace(/ /g, '-'), textContent: st});
  const chip = t.category ? el('span', {className: 'chip', textContent: t.category, style: 'background:' + (t.categoryColour || '#667085')}) : null;
  return el('details', {className: 'task'}, el('summary', {}, el('div', {}, chip, el('span', {className: 'tname', textContent: t.name}), ' ', stChip),
    el('div', {className: 'grade', textContent: t.primaryGrade || ''}), el('div', {className: 'meta', textContent: meta})), body);
}
function render() {
  const q = $('#q').value.trim().toLowerCase();
  const list = DATA.tasks.filter(t => (!yearSel.value || t.year === yearSel.value) && (!subjSel.value || t.subject === subjSel.value)
    && (!$('#status').value || (GROUPS[$('#status').value] || [$('#status').value]).includes(status(t)))
    && (!$('#has').value || HAS[$('#has').value](t)) && (!q || JSON.stringify([t.name, t.subject, t.grades, t.descriptionText]).toLowerCase().includes(q)));
  const bySubject = {};
  list.forEach(t => (bySubject[t.subject] = bySubject[t.subject] || []).push(t));
  $('#list').replaceChildren(...Object.keys(bySubject).sort().map(s => [el('h2', {textContent: s + '  (' + bySubject[s].length + ')'}),
    bySubject[s].sort((a, b) => (b.dueDate || '').localeCompare(a.dueDate || '')).map(taskCard)]).flat(2));
  if (!list.length) $('#list').append(el('p', {className: 'empty', textContent: 'No tasks match.'}));
  const files = list.reduce((n, t) => n + t.attachments.length + t.submissions.length + t.teacherResponses.length, 0);
  $('#stats').replaceChildren(...[['Tasks', list.length], ['Subjects', Object.keys(bySubject).length], ['Completed', list.filter(t => GROUPS.Completed.includes(status(t))).length], ['Overdue', list.filter(t => status(t) === 'Overdue').length], ['Rubrics', list.reduce((n, t) => n + t.rubrics.length, 0)], ['Files', files]]
    .map(([k, v]) => el('div', {className: 'stat'}, el('b', {textContent: v}), k)));
}
yearSel.onchange = () => { refreshSubjects(); render(); };
subjSel.onchange = render; $('#q').oninput = render; $('#status').onchange = render; $('#has').onchange = render;
refreshSubjects(); render();
"""


def _json_for_script(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def write_dashboard(path: Path, tasks: list[dict], student: dict) -> None:
    name = student.get("name") or "Student"
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Compass Portfolio</title><style>{_CSS}</style></head>
<body><header><h1>{html.escape(name)} · Compass portfolio</h1>
<div class="sub">{html.escape(student.get('host') or '')} · {len(tasks)} learning tasks</div>
<div class="stats" id="stats"></div></header>
<main><div class="bar"><select id="year" aria-label="Academic year"><option value="">All years</option></select>
<select id="subject" aria-label="Subject"></select><input type="search" id="q" placeholder="Search tasks, grades, feedback…">
<select id="status" aria-label="Status"><option value="">Any status</option><option>To do</option><option>Overdue</option><option>Due soon</option><option>Completed</option><option>Submitted</option><option>Graded</option></select>
<select id="has" aria-label="Has"><option value="">Anything</option><option value="rubric">Has rubric</option><option value="comment">Has feedback comment</option><option value="submission">Has submission</option><option value="files">Has files</option></select></div>
<div id="list"></div></main>
<script type="application/json" id="data">{_json_for_script({"student": student, "tasks": tasks})}</script>
<script>{_JS}</script></body></html>"""
    path.write_text(doc, encoding="utf-8")


def render_rubric_page(task: dict, rub: dict) -> str:
    e = html.escape
    head = "".join(f"<th>{e(str(c))}</th>" for c in rub["columns"])
    rows = []
    for c in rub["criteria"]:
        cells = []
        for col in rub["columns"]:
            cell = next((x for x in c["cells"] if x["column"] == col), None)
            pts = "".join(f"<li>{e(p)}</li>" for p in (cell or {}).get("points", []) if p)
            cells.append(f'<td class="{"hit" if cell and cell["awarded"] else ""}"><ul>{pts}</ul></td>')
        desc = f'<div class="pre meta">{e(c["description"])}</div>' if c.get("description") else ""
        rows.append(f"<tr><td><b>{e(c['criterion'] or '')}</b>{desc}</td>{''.join(cells)}</tr>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(rub['name'] or 'Rubric')}</title><style>{_CSS} body{{padding:16px}} @media print{{.hit{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}</style></head>
<body><h1>{e(rub['name'] or 'Rubric')}</h1><p class="sub">{e(task['subject'])} · {e(task['name'])} · {e(task.get('year') or '')}</p>
<p class="sub">Highlighted cells are the levels awarded. Use your browser's Print → Save as PDF for a PDF copy.</p>
<div class="scroll"><table class="rub"><tr><th>Criteria</th>{head}</tr>{''.join(rows)}</table></div></body></html>"""
