"""The Overview page: what's new, what's coming up, recent results and a per-subject summary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import changes, insights
from .browse import fmt_date

ID_ROLE = Qt.UserRole + 2


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _latest_result_time(t: dict) -> str:
    return max((g.get("modified") or "" for g in t.get("grades", []) if g.get("display")), default="")


class Overview(QWidget):
    open_task = Signal(object)     # task id
    sync_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.browse = None
        self.c: dict = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)
        top = QHBoxLayout()
        title = QLabel("Overview")
        title.setObjectName("pageTitle")
        self.info = QLabel("")
        self.info.setObjectName("muted")
        self.year = QComboBox()
        self.year.currentIndexChanged.connect(self.refresh)
        top.addWidget(title)
        top.addSpacing(10)
        top.addWidget(self.info, 1)
        top.addWidget(self.year)
        v.addLayout(top)

        self.stats_row = QHBoxLayout()
        self.stats: dict[str, QLabel] = {}
        for key in ("Tasks", "Completed", "Overdue", "With results", "New"):
            card = QFrame()
            card.setObjectName("card")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(14, 10, 14, 10)
            num = QLabel("0")
            f = num.font()
            f.setPointSize(f.pointSize() + 8)
            f.setBold(True)
            num.setFont(f)
            lab = QLabel(key)
            lab.setObjectName("muted")
            cv.addWidget(num)
            cv.addWidget(lab)
            self.stats[key] = num
            self.stats_row.addWidget(card)
        v.addLayout(self.stats_row)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.new_list = self._list_card(grid, 0, 0, "What's new", "Click an item to open the task.")
        self.due_list = self._list_card(grid, 0, 1, "Coming up", "Overdue and due in the next 3 weeks, including your own items.")
        self.recent_list = self._list_card(grid, 1, 0, "Latest results", "Most recently released results.")

        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 10, 14, 10)
        h = QLabel("By subject")
        h.setObjectName("sectionTitle")
        cv.addWidget(h)
        self.subjects = QTreeWidget()
        self.subjects.setRootIsDecorated(False)
        self.subjects.setHeaderLabels(["Subject", "Tasks", "Results", "Latest"])
        hdr = self.subjects.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in (1, 2, 3):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        cv.addWidget(self.subjects)
        grid.addWidget(card, 1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        v.addLayout(grid, 1)

        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        msg = QLabel("Nothing synced yet.\nSign in and run your first sync to see your tasks here.")
        msg.setObjectName("muted")
        msg.setAlignment(Qt.AlignCenter)
        go = QPushButton("Go to Sync")
        go.setObjectName("primary")
        go.clicked.connect(self.sync_requested.emit)
        ev.addStretch(1)
        ev.addWidget(msg)
        ev.addWidget(go, 0, Qt.AlignCenter)
        ev.addStretch(2)
        v.addWidget(self.empty, 1)
        self._content = [self.year, card, self.new_list.parent(), self.due_list.parent(), self.recent_list.parent()]
        self._grid_widgets = grid
        self._stats_cards = [self.stats_row.itemAt(i).widget() for i in range(self.stats_row.count())]
        self._set_loaded(False)

    def _list_card(self, grid, row, col, title, hint) -> QListWidget:
        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 10, 14, 10)
        h = QLabel(title)
        h.setObjectName("sectionTitle")
        cv.addWidget(h)
        lst = QListWidget()
        lst.setObjectName("feed")
        lst.setToolTip(hint)
        lst.itemActivated.connect(self._activate)
        lst.itemClicked.connect(self._activate)
        cv.addWidget(lst, 1)
        grid.addWidget(card, row, col)
        return lst

    def _set_loaded(self, loaded: bool):
        for w in self._content + self._stats_cards:
            w.setVisible(loaded)
        self.empty.setVisible(not loaded)

    def _activate(self, item: QListWidgetItem):
        tid = item.data(ID_ROLE)
        if tid is not None:
            self.open_task.emit(tid)

    def set_source(self, browse):
        """Uses the Browse page's loaded data (tasks, seen markers)."""
        self.browse = browse
        tasks = browse.tasks
        if not tasks:
            self._set_loaded(False)
            return
        years = sorted({t.get("year") or "" for t in tasks}, reverse=True)
        keep = self.year.currentData()
        self.year.blockSignals(True)
        self.year.clear()
        self.year.addItem("All years", "")
        for y in years:
            self.year.addItem(y, y)
        i = self.year.findData(keep) if keep is not None else -1
        self.year.setCurrentIndex(i if i >= 0 else (1 if years else 0))
        self.year.blockSignals(False)
        last = (browse.data.get("lastSync") or {})
        when = _parse(last.get("at"))
        desc = changes.describe(last) if last else ""
        self.info.setText(f"Last synced {fmt_date(last.get('at'))} {when.astimezone():%H:%M}  ·  {desc}" if when else "")
        self._set_loaded(True)
        self.refresh()

    def refresh(self):
        if not self.browse:
            return
        y = self.year.currentData()
        tasks = [t for t in self.browse.tasks if not y or t.get("year") == y]
        seen = self.browse.seen
        new_tasks = [t for t in tasks if changes.unseen(t, seen)]
        planner = self.browse.planner
        sts = [insights.status(t, planner.done) for t in tasks]
        now = datetime.now(timezone.utc)
        entries = [e for e in insights.timeline(self.browse.tasks, planner, now) if not e.hidden and not insights.is_complete(e.status)
                   and e.due and now - timedelta(days=30) <= e.due <= now + timedelta(days=21)]
        overdue = sum(1 for e in entries if e.status == "overdue")
        for key, n in (("Tasks", len(tasks)), ("Completed", sum(insights.is_complete(x) for x in sts)), ("Overdue", overdue),
                       ("With results", sum(1 for t in tasks if any(g.get("display") for g in t.get("grades", [])))), ("New", len(new_tasks))):
            self.stats[key].setText(str(n))

        self.new_list.clear()
        for t in sorted(new_tasks, key=lambda t: max(c["at"] for c in changes.unseen(t, seen)), reverse=True):
            texts = ", ".join(dict.fromkeys(c["text"] for c in changes.unseen(t, seen)))
            self._add(self.new_list, f"{t.get('name')}\n{t.get('subject')} · {texts}", t)
        if not new_tasks:
            self._add(self.new_list, "Nothing new since you last looked.", None)

        self.due_list.clear()
        for e in entries:
            flag = "Overdue" if e.status == "overdue" else insights.status_label(e.status)
            it = self._add(self.due_list, f"{fmt_date(e.due.isoformat())}  ·  {('★ ' if e.kind == 'mine' else '') + e.title}\n{e.subject or 'Your item'}  ·  {flag}", None)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it.setData(ID_ROLE, e.id)
            if e.status == "overdue" and self.c:
                it.setForeground(QColor(self.c["bad"]))
        if not entries:
            self._add(self.due_list, "Nothing due in the next 3 weeks.", None)

        graded = sorted((t for t in tasks if any(g.get("display") for g in t.get("grades", []))),
                        key=lambda t: _latest_result_time(t) or t.get("dueDate") or "", reverse=True)[:25]
        self.recent_list.clear()
        for t in graded:
            grade = t.get("primaryGrade") or next((g["display"] for g in t["grades"] if g.get("display") and not g.get("isComment")), "✓")
            self._add(self.recent_list, f"{grade}  ·  {t.get('name')}\n{t.get('subject')}", t)
        if not graded:
            self._add(self.recent_list, "No results yet.", None)

        self.subjects.clear()
        by: dict[str, list[dict]] = {}
        for t in tasks:
            by.setdefault(t.get("subject") or "Unknown", []).append(t)
        for subj in sorted(by):
            ts = by[subj]
            with_res = [t for t in ts if any(g.get("display") for g in t.get("grades", []))]
            latest = max(with_res, key=lambda t: _latest_result_time(t) or t.get("dueDate") or "", default=None)
            self.subjects.addTopLevelItem(QTreeWidgetItem([subj, str(len(ts)), str(len(with_res)), (latest or {}).get("primaryGrade") or ""]))

    @staticmethod
    def _add(lst: QListWidget, text: str, t: dict | None) -> QListWidgetItem:
        it = QListWidgetItem(text)
        if t is not None:
            it.setData(ID_ROLE, t.get("id"))
        else:
            it.setFlags(Qt.NoItemFlags)
        lst.addItem(it)
        return it
