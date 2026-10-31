"""The Browse page: your synced tasks, grades, feedback, rubrics and files inside the app."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from . import changes, insights, theme

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QSplitter, QTextBrowser, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

TASK_ROLE = Qt.UserRole + 1
STATUS_COLOR = {"overdue": "bad", "due_soon": "accent", "graded": "ok", "submitted": "ok", "done": "ok"}
SEARCH_HELP = ("<b>Search</b> matches task names, subjects, grades, feedback and file names.<br><br>"
               "Add filters:<br>"
               "<code>status:graded</code> &nbsp;submitted, done, overdue, due, pending, completed, todo, new<br>"
               "<code>subject:english</code> &nbsp;<code>year:2025</code> &nbsp;<code>category:assessment</code><br>"
               "<code>has:rubric</code> &nbsp;<code>has:feedback</code> &nbsp;<code>has:submission</code> &nbsp;<code>has:effort</code><br>"
               "Use quotes for phrases: <code>\"running man\"</code>")


def fmt_date(s: str | None) -> str:
    if not s:
        return ""
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone()
        return f"{d.day} {d:%b %Y}"
    except ValueError:
        return s


def _has_results(t: dict) -> bool:
    return any(g.get("display") for g in t.get("grades", []))


def task_html(t: dict, root: Path, c: dict, new_items: list[dict] | None = None, st: str | None = None) -> str:
    """The detail view for one task, styled for QTextBrowser's HTML subset."""
    e = html.escape

    def file_url(rel: str) -> str:
        return QUrl.fromLocalFile(str(root / rel)).toString()

    parts = [f"""<html><head><style>
      body {{ color:{c['text']}; font-size:13px; }}
      h1 {{ font-size:19px; margin:0 0 2px 0; }}
      h3 {{ font-size:12px; color:{c['muted']}; margin:18px 0 6px 0; text-transform:uppercase; }}
      .muted {{ color:{c['muted']}; }}
      table {{ border-collapse:collapse; }}
      td, th {{ border:1px solid {c['line']}; padding:6px 8px; vertical-align:top; }}
      th {{ background:{c['alt']}; text-align:left; }}
      td.label {{ font-weight:600; width:32%; }}
      td.hit {{ background:{c['hit']}; color:{c['hit_text']}; }}
      a {{ color:{c['accent']}; text-decoration:none; }}
      .grade {{ font-size:22px; font-weight:700; color:{c['accent']}; }}
    </style></head><body>"""]
    meta = " · ".join(x for x in [t.get("subject"), t.get("category"), t.get("className"),
                                   f"Due {fmt_date(t.get('dueDate'))}" if t.get("dueDate") else "",
                                   f"Submitted {fmt_date(t.get('submittedTimestamp'))}" if t.get("submittedTimestamp") else ""] if x)
    parts.append(f"<h1>{e(t.get('name') or '')}</h1><div class='muted'>{e(meta)}</div>")
    if st:
        col = c[STATUS_COLOR.get(st, "muted")]
        parts.append(f"<p style='margin:6px 0 0 0'><span style='color:{col}; font-weight:600'>● {e(insights.status_label(st))}</span></p>")
    if new_items:
        lis = "<br>".join("• " + e(n["text"]) for n in new_items)
        parts.append(f"<table width='100%' cellspacing='0' style='margin-top:10px'><tr><td style='border:1px solid {c['accent']};"
                     f"background:{c['alt']}'><b style='color:{c['accent']}'>New since you last looked</b><br>{lis}</td></tr></table>")
    if t.get("primaryGrade"):
        parts.append(f"<p class='grade'>{e(t['primaryGrade'])}</p>")

    grades = [g for g in t.get("grades", []) if g.get("display")]
    parts.append("<h3>Grades &amp; feedback</h3>")
    if grades:
        rows = "".join(
            f"<tr><td class='label'>{e(g.get('item') or '')}</td><td>{e(g['display']).replace(chr(10), '<br>')}</td></tr>" for g in grades)
        parts.append(f"<table width='100%' cellspacing='0'>{rows}</table>")
    else:
        parts.append("<p class='muted'><i>No results released.</i></p>")

    for r in t.get("rubrics", []):
        link = f" &nbsp;<a href='{file_url(r['path'])}'>open / print</a>" if r.get("path") else ""
        parts.append(f"<h3>Rubric: {e(r.get('name') or '')}{link}</h3>")
        head = "".join(f"<th>{e(str(col))}</th>" for col in r["columns"])
        body = []
        for crit in r["criteria"]:
            cells = []
            for col in r["columns"]:
                cell = next((x for x in crit["cells"] if x["column"] == col), None)
                pts = "<br>".join("• " + e(p) for p in (cell or {}).get("points", []) if p)
                cells.append(f"<td class='{'hit' if cell and cell.get('awarded') else ''}'>{pts}</td>")
            body.append(f"<tr><td class='label'>{e(crit.get('criterion') or '')}</td>{''.join(cells)}</tr>")
        parts.append(f"<table width='100%' cellspacing='0'><tr><th>Criteria</th>{head}</tr>{''.join(body)}</table>")

    for key, title in (("attachments", "Attachments"), ("submissions", "Submissions"), ("teacherResponses", "Teacher responses")):
        files = t.get(key) or []
        if not files:
            continue
        items = []
        for f in files:
            name = e(f.get("fileName") or f.get("name") or "file")
            when = fmt_date(f.get("submitted") or f.get("uploaded"))
            if f.get("path"):
                item = f"<a href='{file_url(f['path'])}'>{name}</a>"
            elif f.get("link"):
                item = f"<a href='{e(f['link'])}'>{e(f['link'])}</a>"
            else:
                item = f"{name} <span class='muted'>(not downloaded)</span>"
            if f.get("error"):
                item += f" <span style='color:{c['bad']}'>download failed</span>"
            items.append(f"{item} <span class='muted'>{e(when)}</span>")
        parts.append(f"<h3>{title}</h3>" + "<br>".join(items))

    if t.get("descriptionText"):
        parts.append("<h3>Task description</h3><div>" + e(t["descriptionText"]).replace("\n", "<br>") + "</div>")
    if t.get("folder"):
        parts.append(f"<p class='muted' style='margin-top:18px'><a href='{file_url(t['folder'])}'>Open task folder</a></p>")
    parts.append("</body></html>")
    return "".join(parts)


def feedback_text(t: dict) -> str:
    """Plain-text copy of a task's results and feedback."""
    lines = [t.get("name") or "", f"{t.get('subject') or ''} · {t.get('year') or ''}", ""]
    for g in t.get("grades", []):
        if g.get("display"):
            sep = "\n" if g.get("isComment") else " "
            lines.append(f"{g.get('item')}:{sep}{g['display']}")
    for r in t.get("rubrics", []):
        lines += ["", f"Rubric: {r.get('name')}"] + [f"  {c.get('criterion')}: {c.get('awarded') or '-'}" for c in r.get("criteria", [])]
    return "\n".join(lines).strip() + "\n"


class BrowsePage(QWidget):
    seen_changed = Signal()
    planner_changed = Signal()

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.root: Path | None = None
        self.tasks: list[dict] = []
        self.data: dict = {}
        self.seen: set[str] = set()
        self.planner = insights.Planner()

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        top = QHBoxLayout()
        title = QLabel("Browse")
        title.setObjectName("pageTitle")
        self.info = QLabel("")
        self.info.setObjectName("muted")
        top.addWidget(title)
        top.addSpacing(10)
        top.addWidget(self.info, 1)
        self.open_html = QPushButton("Open HTML portfolio")
        self.open_html.clicked.connect(lambda: self.root and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root / "index.html"))))
        self.open_dir = QPushButton("Open folder")
        self.open_dir.clicked.connect(lambda: self.root and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root))))
        top.addWidget(self.open_html)
        top.addWidget(self.open_dir)
        v.addLayout(top)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…  try  essay status:graded has:rubric subject:english")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip(SEARCH_HELP)
        self.search.setMinimumWidth(180)
        self.year = theme.Combo()
        self.subject = theme.Combo()
        self.state = theme.Combo()
        self.state.addItem("Any status", "")
        for name in insights.STATUS_FILTERS:
            self.state.addItem(name, name)
        self.score_type = theme.Combo()
        self.only_new = QCheckBox("New")
        filters.addWidget(self.search, 3)
        filters.addWidget(self.year, 1)
        filters.addWidget(self.subject, 1)
        filters.addWidget(self.state, 1)
        filters.addWidget(self.score_type, 1)
        filters.addWidget(self.only_new)
        v.addLayout(filters)

        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Task", "Status", "Result", "Due"])
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 3):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        self.tree.setColumnWidth(2, 70)
        self.tree.setTextElideMode(Qt.ElideRight)
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.anchorClicked.connect(QDesktopServices.openUrl)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        actions = QHBoxLayout()
        self.copy_btn = QPushButton("Copy feedback")
        self.copy_btn.clicked.connect(self._copy)
        self.pdf_btn = QPushButton("Save as PDF…")
        self.pdf_btn.clicked.connect(self._pdf)
        self.done_btn = QPushButton("Mark done")
        self.done_btn.setToolTip("For tasks with nothing to submit online. Graded and submitted tasks count as done automatically.")
        self.done_btn.clicked.connect(self._toggle_done)
        self.task_dir_btn = QPushButton("Task folder")
        self.task_dir_btn.clicked.connect(lambda: self.current_task() and self.root and QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.root / self.current_task()["folder"]))))
        self.status = QLabel("")
        self.status.setObjectName("muted")
        actions.addWidget(self.copy_btn)
        actions.addWidget(self.pdf_btn)
        actions.addWidget(self.task_dir_btn)
        actions.addWidget(self.done_btn)
        actions.addWidget(self.status, 1)
        rv.addLayout(actions)
        rv.addWidget(self.detail, 1)
        self.right = right
        split.addWidget(self.tree)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([520, 600])
        v.addWidget(split, 1)

        self.empty = QLabel("Nothing synced yet. Sign in and run a sync, and your tasks will show up here.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)

        self.search.textChanged.connect(self.refresh)
        self.year.currentIndexChanged.connect(self._year_changed)
        self.subject.currentIndexChanged.connect(self.refresh)
        self.state.currentIndexChanged.connect(self.refresh)
        self.score_type.currentIndexChanged.connect(self.refresh)
        self.only_new.toggled.connect(self.refresh)
        self.tree.currentItemChanged.connect(self._show)
        self._set_loaded(False)

    def _set_loaded(self, loaded: bool):
        for w in (self.tree, self.right, self.search, self.year, self.subject, self.state, self.score_type, self.only_new, self.open_html, self.open_dir):
            w.setVisible(loaded)
        self.empty.setVisible(not loaded)

    def set_colors(self, colors: dict):
        self.colors = colors
        if self.tasks:
            keep = self.current_task()
            self.refresh()
            if keep:
                self.select_task(keep.get("id"))

    def load(self, root: Path) -> bool:
        data_file = Path(root) / "data.json"
        if not data_file.exists():
            return False
        data = json.loads(data_file.read_text(encoding="utf-8"))
        self.root = Path(root)
        self.data = data
        self.tasks = data.get("tasks", [])
        self.seen = changes.load_seen(self.root)
        self.planner = insights.Planner.load(self.root)
        m = datetime.fromtimestamp(data_file.stat().st_mtime)
        when = f"{m.day} {m:%b %Y, %H:%M}"
        self.info.setText(f"{len(self.tasks)} tasks · synced {when}")
        years = sorted({t.get("year") or "" for t in self.tasks}, reverse=True)
        self.year.blockSignals(True)
        self.year.clear()
        self.year.addItem("All years", "")
        for y in years:
            self.year.addItem(y, y)
        self.year.setCurrentIndex(1 if years else 0)
        self.year.blockSignals(False)
        self._year_changed()
        self._set_loaded(True)
        return True

    def _year_changed(self):
        y = self.year.currentData()
        keep = self.subject.currentData()
        subjects = sorted({t.get("subject") or "" for t in self.tasks if not y or t.get("year") == y})
        self.subject.blockSignals(True)
        self.subject.clear()
        self.subject.addItem("All subjects", "")
        for s in subjects:
            self.subject.addItem(s, s)
        idx = self.subject.findData(keep)
        self.subject.setCurrentIndex(idx if idx >= 0 else 0)
        self.subject.blockSignals(False)
        keep = self.score_type.currentData()
        self.score_type.blockSignals(True)
        self.score_type.clear()
        self.score_type.addItem("Any score type", "")
        for name in insights.score_types([t for t in self.tasks if not y or t.get("year") == y]) + ["Has rubric", "Has feedback comment"]:
            self.score_type.addItem(name, name)
        idx = self.score_type.findData(keep)
        self.score_type.setCurrentIndex(idx if idx >= 0 else 0)
        self.score_type.blockSignals(False)
        self.refresh()

    def refresh(self):
        q = insights.parse_query(self.search.text())
        y, s = self.year.currentData(), self.subject.currentData()
        wanted = insights.STATUS_FILTERS.get(self.state.currentData())
        kind = self.score_type.currentData()
        shown = [t for t in self.tasks
                 if (not y or t.get("year") == y) and (not s or t.get("subject") == s)
                 and (not wanted or self.status_of(t) in wanted)
                 and (not kind or insights.has_score_type(t, kind))
                 and (not self.only_new.isChecked() or changes.unseen(t, self.seen))
                 and insights.matches(t, q, self.status_of(t), bool(changes.unseen(t, self.seen)))]
        current = self.tree.currentItem().data(0, TASK_ROLE).get("id") if self.tree.currentItem() and self.tree.currentItem().data(0, TASK_ROLE) else None
        self.tree.clear()
        by_subject: dict[str, list[dict]] = {}
        for t in shown:
            by_subject.setdefault(t.get("subject") or "Unknown", []).append(t)
        select = None
        for subj in sorted(by_subject):
            tasks = sorted(by_subject[subj], key=lambda t: t.get("dueDate") or "", reverse=True)
            parent = QTreeWidgetItem([f"{subj}  ({len(tasks)})", "", ""])
            f = parent.font(0)
            f.setBold(True)
            parent.setFont(0, f)
            parent.setFlags(parent.flags() & ~Qt.ItemIsSelectable)
            for t in tasks:
                st = self.status_of(t)
                child = QTreeWidgetItem([t.get("name") or "", insights.status_label(st),
                                         t.get("primaryGrade") or ("✓" if _has_results(t) else ""), fmt_date(t.get("dueDate"))])
                child.setToolTip(2, child.text(2))
                col = STATUS_COLOR.get(st)
                if col:
                    child.setForeground(1, QBrush(QColor(self.colors[col])))
                child.setData(0, TASK_ROLE, t)
                child.setToolTip(0, t.get("name") or "")
                self._style_item(child, t)
                parent.addChild(child)
                if t.get("id") == current:
                    select = child
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)
        if select is None and self.tree.topLevelItemCount() and self.tree.topLevelItem(0).childCount():
            select = self.tree.topLevelItem(0).child(0)
        if select:
            self.tree.setCurrentItem(select)
        else:
            self.detail.setHtml(f"<p style='color:{self.colors['muted']}'>No tasks match.</p>")

    # ── helpers ──────────────────────────────────────────────────────
    def status_of(self, t: dict) -> str:
        return insights.status(t, self.planner.done)

    def _toggle_done(self):
        t = self.current_task()
        if t:
            self.planner.toggle_done(t.get("id"))
            self.refresh()
            self.select_task(t.get("id"))
            self.planner_changed.emit()

    def unseen_count(self) -> int:
        return sum(1 for t in self.tasks if changes.unseen(t, self.seen))

    def current_task(self) -> dict | None:
        it = self.tree.currentItem()
        return it.data(0, TASK_ROLE) if it else None

    def _style_item(self, item, t):
        new = bool(changes.unseen(t, self.seen))
        f = item.font(0)
        f.setBold(new)
        item.setFont(0, f)
        item.setText(0, ("● " if new else "") + (t.get("name") or ""))
        item.setForeground(0, QBrush(QColor(self.colors["accent"])) if new else QBrush())

    def select_task(self, task_id) -> bool:
        """Shows one task, clearing filters that would hide it."""
        t = next((x for x in self.tasks if x.get("id") == task_id), None)
        if not t:
            return False
        self.search.clear()
        self.state.setCurrentIndex(0)
        self.score_type.setCurrentIndex(0)
        self.only_new.setChecked(False)
        i = self.year.findData(t.get("year"))
        if self.year.currentIndex() != i:
            self.year.setCurrentIndex(i)
        if self.subject.currentData():
            self.subject.setCurrentIndex(0)
        for p in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(p)
            for c in range(parent.childCount()):
                if parent.child(c).data(0, TASK_ROLE).get("id") == task_id:
                    self.tree.setCurrentItem(parent.child(c))
                    return True
        return False

    def _show(self, item, _prev=None):
        t = item.data(0, TASK_ROLE) if item else None
        for b in (self.copy_btn, self.pdf_btn, self.task_dir_btn):
            b.setEnabled(bool(t))
        st = self.status_of(t) if t else ""
        self.done_btn.setVisible(bool(t) and st not in ("graded", "submitted"))
        self.done_btn.setText("Not done" if st == "done" else "Mark done")
        self.status.setText("")
        if t and self.root:
            new_items = changes.unseen(t, self.seen)
            self.detail.setHtml(task_html(t, self.root, self.colors, new_items, st))
            self._mark_seen(item)

    def _mark_seen(self, item):
        """Opening a task marks its changes as seen, but only once the page is actually on screen."""
        t = item.data(0, TASK_ROLE) if item else None
        if not t or not self.root or not self.isVisible():
            return
        new_items = changes.unseen(t, self.seen)
        if new_items:
            self.seen.update(changes.seen_key(t, c) for c in new_items)
            changes.save_seen(self.root, self.seen)
            self._style_item(item, t)
            self.seen_changed.emit()

    def showEvent(self, e):
        super().showEvent(e)
        self._mark_seen(self.tree.currentItem())

    def _copy(self):
        t = self.current_task()
        if t:
            QApplication.clipboard().setText(feedback_text(t))
            self.status.setText("Copied.")

    def _pdf(self):
        t = self.current_task()
        if not t:
            return
        from .scrape import safe_name
        default = str(Path.home() / "Documents" / f"{safe_name(t.get('name'), 80)}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save task as PDF", default, "PDF (*.pdf)")
        if not path:
            return
        self.export_pdf(t, path)
        self.status.setText(f"Saved {Path(path).name}")

    def export_pdf(self, t: dict, path: str):
        """Prints the task view (always in light colours) to a PDF."""
        from PySide6.QtGui import QTextDocument
        from .theme import LIGHT
        doc = QTextDocument()
        doc.setHtml(task_html(t, self.root, LIGHT))
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        printer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, printer.pageLayout().margins()))
        doc.print_(printer)
