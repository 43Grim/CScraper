"""Universal search (Ctrl+K): find any task across every year, with the same filters as Browse."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from . import changes, insights
from .browse import SEARCH_HELP, fmt_date

ID_ROLE = Qt.UserRole + 4
LIMIT = 200


class QuickFind(QDialog):
    chosen = Signal(object)   # task id

    def __init__(self, browse, parent=None):
        super().__init__(parent)
        self.browse = browse
        self.setWindowTitle("Search everything")
        self.setMinimumSize(640, 460)
        v = QVBoxLayout(self)
        self.box = QLineEdit()
        self.box.setPlaceholderText("Search every task…  e.g.  status:overdue  ·  has:rubric english  ·  \"running man\"")
        self.box.setClearButtonEnabled(True)
        self.box.setToolTip(SEARCH_HELP)
        self.list = QListWidget()
        self.list.setObjectName("feed")
        self.count = QLabel("")
        self.count.setObjectName("muted")
        v.addWidget(self.box)
        v.addWidget(self.list, 1)
        v.addWidget(self.count)
        self.box.textChanged.connect(self.refresh)
        self.box.returnPressed.connect(self._pick_current)
        self.list.itemActivated.connect(self._pick)
        self.list.itemClicked.connect(self._pick)
        self.refresh()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up) and self.box.hasFocus():
            row = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return
        super().keyPressEvent(e)

    def results(self, text: str) -> list[dict]:
        q = insights.parse_query(text)
        tasks = self.browse.tasks
        out = [t for t in tasks if insights.matches(t, q, self.browse.status_of(t), bool(changes.unseen(t, self.browse.seen)))]
        return sorted(out, key=lambda t: t.get("dueDate") or "", reverse=True)

    def refresh(self):
        text = self.box.text()
        found = self.results(text)
        self.list.clear()
        for t in found[:LIMIT]:
            st = insights.status_label(self.browse.status_of(t))
            grade = f"  ·  {t['primaryGrade']}" if t.get("primaryGrade") else ""
            it = QListWidgetItem(f"{t.get('name')}\n{t.get('subject')}  ·  {t.get('year')}  ·  due {fmt_date(t.get('dueDate')) or '–'}  ·  {st}{grade}")
            it.setData(ID_ROLE, t.get("id"))
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        more = f" (showing {LIMIT})" if len(found) > LIMIT else ""
        self.count.setText(f"{len(found)} task{'s' * (len(found) != 1)}{more}  ·  Enter opens  ·  ↑↓ to move  ·  Esc closes")

    def _pick_current(self):
        if self.list.currentItem():
            self._pick(self.list.currentItem())

    def _pick(self, item):
        self.chosen.emit(item.data(ID_ROLE))
        self.accept()
