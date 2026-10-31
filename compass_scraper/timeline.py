"""The Timeline page: every due date in one list, plus your own items, with mark-done / remove."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import insights
from .insights import Entry

ENTRY_ROLE = Qt.UserRole + 3
OLD_OVERDUE_DAYS = 30


class ItemDialog(QDialog):
    def __init__(self, subjects: list[str], item: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit item" if item else "Add to timeline")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.title = QLineEdit((item or {}).get("title", ""))
        self.title.setPlaceholderText("e.g. Study for the maths test")
        self.when = QDateTimeEdit()
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("d MMM yyyy  h:mm ap")
        due = insights.parse_dt((item or {}).get("due"))
        self.when.setDateTime(QDateTime(due.astimezone()) if due else QDateTime.currentDateTime().addDays(1))
        self.subject = QComboBox()
        self.subject.setEditable(True)
        self.subject.addItems([""] + subjects)
        self.subject.setCurrentText((item or {}).get("subject", ""))
        self.notes = QPlainTextEdit((item or {}).get("notes", ""))
        self.notes.setMaximumHeight(80)
        form.addRow("Title", self.title)
        form.addRow("Due", self.when)
        form.addRow("Subject", self.subject)
        form.addRow("Notes", self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _ok(self):
        if self.title.text().strip():
            self.accept()
        else:
            self.title.setFocus()

    def values(self) -> dict:
        due = self.when.dateTime().toPython().astimezone()
        return {"title": self.title.text().strip(), "due": due.isoformat(), "subject": self.subject.currentText().strip(),
                "notes": self.notes.toPlainText().strip()}


class TimelinePage(QWidget):
    open_task = Signal(object)
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.browse = None
        self.c: dict = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(10)
        top = QHBoxLayout()
        title = QLabel("Timeline")
        title.setObjectName("pageTitle")
        self.info = QLabel("")
        self.info.setObjectName("muted")
        self.add_btn = QPushButton("Add item…")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.add_item)
        self.ics_btn = QPushButton("Export calendar…")
        self.ics_btn.setToolTip("Save due dates as an .ics file for Google, Apple or Outlook Calendar")
        self.ics_btn.clicked.connect(self._export)
        top.addWidget(title)
        top.addSpacing(10)
        top.addWidget(self.info, 1)
        top.addWidget(self.ics_btn)
        top.addWidget(self.add_btn)
        v.addLayout(top)

        filters = QHBoxLayout()
        self.subject = QComboBox()
        self.show_done = QCheckBox("Completed")
        self.show_past = QCheckBox("Past")
        self.show_hidden = QCheckBox("Removed")
        self.show_done.setToolTip("Also show graded, submitted and done items")
        self.show_past.setToolTip(f"Also show anything due more than {OLD_OVERDUE_DAYS} days ago")
        self.show_hidden.setToolTip("Show Compass tasks you removed from the timeline, so you can restore them")
        lab = QLabel("Show:")
        lab.setObjectName("muted")
        filters.addWidget(self.subject, 1)
        filters.addSpacing(12)
        filters.addWidget(lab)
        for w in (self.show_done, self.show_past, self.show_hidden):
            filters.addWidget(w)
        filters.addStretch(2)
        v.addLayout(filters)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Task", "Subject", "Due", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._activate(it))
        self.tree.currentItemChanged.connect(lambda *_: self._sync_buttons())
        v.addWidget(self.tree, 1)

        acts = QHBoxLayout()
        self.open_btn = QPushButton("Open task")
        self.open_btn.clicked.connect(lambda: self._activate(self.tree.currentItem()))
        self.done_btn = QPushButton("Mark done")
        self.done_btn.clicked.connect(lambda: self._toggle_done(self._current()))
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setObjectName("danger")
        self.remove_btn.clicked.connect(lambda: self._remove(self._current()))
        hint = QLabel("Double-click to open. Right-click for more. Removing a Compass task only hides it here.")
        hint.setObjectName("muted")
        for w in (self.open_btn, self.done_btn, self.remove_btn):
            acts.addWidget(w)
        acts.addSpacing(10)
        acts.addWidget(hint, 1)
        v.addLayout(acts)

        for w in (self.show_done, self.show_past, self.show_hidden):
            w.toggled.connect(self.refresh)
        self.subject.currentIndexChanged.connect(self.refresh)
        self._sync_buttons()

    # data
    @property
    def planner(self) -> insights.Planner:
        return self.browse.planner

    def set_colors(self, c: dict):
        self.c = c
        self.refresh()

    def set_source(self, browse):
        self.browse = browse
        keep = self.subject.currentData()
        self.subject.blockSignals(True)
        self.subject.clear()
        self.subject.addItem("All subjects", "")
        for s in self._subjects():
            self.subject.addItem(s, s)
        i = self.subject.findData(keep)
        self.subject.setCurrentIndex(i if i >= 0 else 0)
        self.subject.blockSignals(False)
        self.refresh()

    def _subjects(self) -> list[str]:
        if not self.browse:
            return []
        latest = max((t.get("year") or "" for t in self.browse.tasks), default="")
        return sorted({t.get("subject") for t in self.browse.tasks if t.get("year") == latest and t.get("subject")}
                      | {i.get("subject") for i in self.planner.items if i.get("subject")})

    def entries(self) -> list[Entry]:
        return insights.timeline(self.browse.tasks, self.planner) if self.browse and self.browse.root else []

    def refresh(self):
        if not self.browse or not self.c:
            return
        now = insights.now()
        cut = now - timedelta(days=OLD_OVERDUE_DAYS)
        subj = self.subject.currentData()
        groups: dict[str, list[Entry]] = {}
        counts = {"overdue": 0, "soon": 0}
        for e in self.entries():
            if e.hidden and not self.show_hidden.isChecked():
                continue
            if subj and e.subject != subj:
                continue
            b = insights.bucket(e, now)
            if b == "Overdue" and e.due and e.due < cut:
                b = "Earlier"
            done = insights.is_complete(e.status)
            if b == "Overdue":
                counts["overdue"] += 1
            elif b in ("Today", "Tomorrow", "This week") and not done:
                counts["soon"] += 1
            if done and not self.show_done.isChecked() and not e.hidden:
                continue
            if b in ("Earlier", "No due date") and not self.show_past.isChecked() and not e.hidden:
                continue
            groups.setdefault(b, []).append(e)
        self.info.setText(f"{counts['overdue']} overdue  ·  {counts['soon']} due this week")

        keep = self._current()
        keep_id = keep.id if keep else None
        self.tree.clear()
        bold = self.tree.font()
        bold.setBold(True)
        select = None
        for b in insights.BUCKETS:
            items = groups.get(b) or []
            if not items:
                continue
            if b == "Earlier":
                items = list(reversed(items))
            head = QTreeWidgetItem([f"{b}  ({len(items)})", "", "", ""])
            head.setFont(0, bold)
            head.setFlags(Qt.ItemIsEnabled)
            if b == "Overdue":
                head.setForeground(0, QBrush(QColor(self.c["bad"])))
            self.tree.addTopLevelItem(head)
            for e in items:
                it = self._row(e)
                self.tree.addTopLevelItem(it)
                if e.id == keep_id:
                    select = it
        if not self.tree.topLevelItemCount():
            empty = QTreeWidgetItem(["Nothing coming up. Add your own items with “Add item…”.", "", "", ""])
            empty.setFlags(Qt.NoItemFlags)
            self.tree.addTopLevelItem(empty)
        if select:
            self.tree.setCurrentItem(select)
        self._sync_buttons()

    def _row(self, e: Entry) -> QTreeWidgetItem:
        due = ""
        if e.due:
            d = e.due.astimezone()
            due = f"{d:%a} {d.day} {d:%b}" + (f"  {d:%H:%M}" if (d.hour, d.minute) not in ((0, 0), (23, 59)) else "")
            if d.year != datetime.now().year:
                due += f" {d.year}"
        title = ("★ " if e.kind == "mine" else "") + e.title + ("  (removed)" if e.hidden else "")
        it = QTreeWidgetItem(["    " + title, e.subject, due, insights.status_label(e.status)])
        it.setData(0, ENTRY_ROLE, e)
        it.setToolTip(0, (e.item or {}).get("notes") or e.title)
        col = {"overdue": self.c["bad"], "due_soon": self.c["accent"], "graded": self.c["ok"], "submitted": self.c["ok"],
               "done": self.c["ok"]}.get(e.status)
        if col:
            it.setForeground(3, QBrush(QColor(col)))
        if insights.is_complete(e.status) or e.hidden:
            for i in range(3):
                it.setForeground(i, QBrush(QColor(self.c["muted"])))
            f = it.font(0)
            f.setStrikeOut(e.status == "done")
            it.setFont(0, f)
        return it

    def _current(self) -> Entry | None:
        it = self.tree.currentItem()
        return it.data(0, ENTRY_ROLE) if it else None

    def _sync_buttons(self):
        e = self._current()
        self.open_btn.setEnabled(bool(e))
        self.open_btn.setText("Edit…" if e and e.kind == "mine" else "Open task")
        can_done = bool(e) and e.status not in ("graded", "submitted")
        self.done_btn.setEnabled(can_done)
        self.done_btn.setText("Not done" if e and e.status == "done" else "Mark done")
        self.remove_btn.setEnabled(bool(e))
        self.remove_btn.setText("Restore" if e and e.hidden else "Delete" if e and e.kind == "mine" else "Remove")

    # actions
    def _activate(self, it):
        e = it.data(0, ENTRY_ROLE) if it else None
        if not e:
            return
        if e.kind == "compass":
            self.open_task.emit(e.id)
        else:
            self.edit_item(e)

    def add_item(self):
        if not self.browse or not self.browse.root:
            return
        dlg = ItemDialog(self._subjects(), parent=self)
        if self.subject.currentData():
            dlg.subject.setCurrentText(self.subject.currentData())
        if dlg.exec() == QDialog.Accepted:
            self.planner.add(**dlg.values())
            self._changed()

    def edit_item(self, e: Entry):
        dlg = ItemDialog(self._subjects(), e.item, self)
        if dlg.exec() == QDialog.Accepted:
            self.planner.update(e.id, **dlg.values())
            self._changed()

    def _toggle_done(self, e: Entry | None):
        if e:
            self.planner.toggle_done(e.id)
            self._changed()

    def _remove(self, e: Entry | None):
        if not e:
            return
        if e.hidden:
            self.planner.hidden.discard(e.id)
            self.planner.save()
        else:
            self.planner.remove(e.id)
        self._changed()

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        e = it.data(0, ENTRY_ROLE) if it else None
        m = QMenu(self)
        if e:
            self.tree.setCurrentItem(it)
            m.addAction("Open task" if e.kind == "compass" else "Edit…", lambda: self._activate(it))
            if e.status not in ("graded", "submitted"):
                m.addAction("Not done" if e.status == "done" else "Mark done", lambda: self._toggle_done(e))
            m.addAction("Restore" if e.hidden else "Delete" if e.kind == "mine" else "Remove from timeline", lambda: self._remove(e))
            m.addSeparator()
        m.addAction("Add item…", self.add_item)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _export(self):
        if not self.browse or not self.browse.root:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export due dates", str(Path.home() / "Compass due dates.ics"), "Calendar (*.ics)")
        if path:
            self.export_ics(path)

    def export_ics(self, path: str) -> int:
        now = insights.now() - timedelta(days=OLD_OVERDUE_DAYS)
        entries = [e for e in self.entries() if not e.hidden and e.due and e.due >= now]
        Path(path).write_text(insights.to_ics(entries, self.browse.data.get("student", {}).get("host") or "compass"), encoding="utf-8")
        self.info.setText(f"Exported {len(entries)} due dates to {Path(path).name}")
        return len(entries)

    def _changed(self):
        self.refresh()
        self.changed.emit()
