"""The Performance page: graphs of every assessment result for one academic year."""
from __future__ import annotations

import math
import re
from collections import Counter

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import insights
from .charts import BarChart, TimelineChart, series_colors


# Expected-level bands, coloured like a school achievement sheet (light, dark).
LEVEL_COLORS = {
    "Below": ("#fda4af", "#881337"), "Towards": ("#fca5a5", "#7f1d1d"), "At": ("#86efac", "#14532d"),
    "Above": ("#67e8f9", "#155e75"), "Well above": ("#d8b4fe", "#581c87"),
}
TASK_ROLE = Qt.UserRole + 5


def _card(title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    v = QVBoxLayout(card)
    v.setContentsMargins(14, 10, 14, 12)
    t = QLabel(title)
    t.setObjectName("sectionTitle")
    t.setToolTip(hint)
    v.addWidget(t)
    if hint:
        m = QLabel(hint)
        m.setObjectName("muted")
        m.setWordWrap(True)
        v.addWidget(m)
    return card, v


class PerformancePage(QWidget):
    open_task = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.browse = None
        self.c: dict = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)
        top = QHBoxLayout()
        title = QLabel("Performance")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        top.addSpacing(16)
        self.year, self.kind, self.axis, self.category = QComboBox(), QComboBox(), QComboBox(), QComboBox()
        self.axis.addItem("By task", "index")
        self.axis.addItem("By due date", "date")
        for tip, w in (("Academic year", self.year), ("Which marks to graph", self.kind), ("X axis", self.axis),
                       ("Task category", self.category)):
            w.setToolTip(tip)
            w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(6)
            top.addWidget(w, 1)
        v.addLayout(top)

        stats = QHBoxLayout()
        self.stats: dict[str, tuple[QLabel, QLabel]] = {}
        for key in ("Graded", "Average", "Strongest", "Trend", "Completed"):
            card = QFrame()
            card.setObjectName("card")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(14, 10, 14, 10)
            num = QLabel("–")
            f = num.font()
            f.setPointSize(f.pointSize() + 6)
            f.setBold(True)
            num.setFont(f)
            num.setWordWrap(True)
            sub = QLabel(key)
            sub.setObjectName("muted")
            sub.setWordWrap(True)
            cv.addWidget(num)
            cv.addWidget(sub)
            self.stats[key] = (num, sub)
            stats.addWidget(card, 1)
        v.addLayout(stats)

        grid = QGridLayout()
        grid.setSpacing(12)
        card, cv = _card("Results over the year", "Click a subject to show or hide it, or a point to open the task.")
        self.trend = TimelineChart()
        self.trend.point_clicked.connect(self.open_task.emit)
        cv.addWidget(self.trend, 1)
        grid.addWidget(card, 0, 0, 1, 2)

        card, cv = _card("Results table", "Coloured by level. Double-click a mark to open the task.")
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.cellDoubleClicked.connect(self._cell_open)
        cv.addWidget(self.table, 1)
        self.key = QHBoxLayout()
        self.key_labels: dict[str, QLabel] = {}
        k = QLabel("Key")
        k.setObjectName("muted")
        self.key.addWidget(k)
        for name in ("Towards", "At", "Above", "Well above"):
            lab = QLabel(name)
            lab.setAlignment(Qt.AlignCenter)
            self.key_labels[name] = lab
            self.key.addWidget(lab, 1)
        cv.addLayout(self.key)
        grid.addWidget(card, 1, 0)

        side = QVBoxLayout()
        side.setSpacing(12)
        card, cv = _card("Average by subject")
        self.subjects = BarChart()
        self.subjects.fixed_row = 26
        scroll = QScrollArea()
        scroll.setObjectName("plain")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.subjects)
        cv.addWidget(scroll, 1)
        side.addWidget(card, 3)
        card, cv = _card("Results breakdown", "All level results this year (assessments and assignments)")
        self.dist = BarChart()
        self.dist.setMinimumHeight(96)
        cv.addWidget(self.dist, 1)
        side.addWidget(card, 2)
        grid.addLayout(side, 1, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        v.addLayout(grid, 1)

        self.year.currentIndexChanged.connect(self._year_changed)
        for w in (self.kind, self.axis, self.category):
            w.currentIndexChanged.connect(self.refresh)

    def set_colors(self, c: dict):
        self.c = c
        for ch in (self.trend, self.subjects, self.dist):
            ch.set_colors(c)
        dark = QColor(c["window"]).lightness() < 128
        for name, lab in self.key_labels.items():
            bg = LEVEL_COLORS[name][dark]
            lab.setStyleSheet(f"background:{bg}; color:{'#f4f4f5' if dark else '#18181b'}; border-radius:4px; padding:3px 6px;")
        self.refresh()

    def set_source(self, browse):
        self.browse = browse
        years = sorted({t.get("year") or "" for t in browse.tasks}, reverse=True)
        keep = self.year.currentData()
        self.year.blockSignals(True)
        self.year.clear()
        for y in years:
            self.year.addItem(y, y)
        i = self.year.findData(keep)
        self.year.setCurrentIndex(i if i >= 0 else 0)
        self.year.blockSignals(False)
        self._year_changed()

    def _year_tasks(self) -> list[dict]:
        y = self.year.currentData()
        return [t for t in (self.browse.tasks if self.browse else []) if t.get("year") == y and insights.counts_for_performance(t)]

    def _year_changed(self):
        tasks = self._year_tasks()
        for combo, values, first in ((self.kind, insights.score_types(tasks) or [insights.VC], None),
                                     (self.category, sorted({t.get("category") or "" for t in tasks} - {""}), "Assessments & assignments")):
            keep = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            if first:
                combo.addItem(first, "")
            for val in values:
                combo.addItem(val, val)
            i = combo.findData(keep)
            combo.setCurrentIndex(i if i >= 0 else 0)
            combo.blockSignals(False)
        self.refresh()

    def refresh(self):
        if not self.browse or not self.c:
            return
        tasks = self._year_tasks()
        subjects = sorted({t.get("subject") or "Unknown" for t in tasks})
        palette = series_colors(self.c)
        color_of = {s: (palette[i] if i < len(palette) else self.c["muted"]) for i, s in enumerate(subjects)}
        cat = self.category.currentData()
        if cat:
            tasks = [t for t in tasks if t.get("category") == cat]
        kind = self.kind.currentData() or insights.VC
        pct = kind in insights.PERCENT_CATEGORIES
        what = {insights.VC: "VCE number score", insights.SAC: "SAC", insights.EXAM: "exam"}[kind]
        by_index = self.axis.currentData() == "index"

        done = self.browse.planner.done if getattr(self.browse, "planner", None) else set()
        complete = sum(insights.is_complete(insights.status(t, done)) for t in tasks)
        self._stat("Completed", f"{complete}/{len(tasks)}" if tasks else "–", "Completed (graded, submitted or done)")

        # results breakdown: every level label this year, whatever the marks
        levels = Counter()
        for t in tasks:
            for g in t.get("grades", []):
                sc = insights.score(g)
                if sc and sc.kind == "scheme" and re.search(r"level|standard|expected", sc.label, re.I):
                    levels[(sc.value, sc.label)] += 1
        if levels:
            top = max(levels.values())
            self.dist.set_data([(lab, n, str(n), self.c["accent"], f"{lab}: {n} result{'s' * (n != 1)}")
                                for (val, lab), n in sorted(levels.items(), key=lambda x: -x[0][0])], 0, top)
        else:
            self.dist.set_data([], message="No level results this year.")

        scored = []
        for t in tasks:
            s = insights.task_score(t, kind)
            due = insights.parse_dt(t.get("dueDate")) or insights.parse_dt(t.get("created"))
            if s and due:
                scored.append((t, s, due))
        if not scored:
            msg = f"No {what} marks for this year yet." if tasks else "No assessments or assignments for this year."
            self.trend.set_data([], 0, 100, [], msg)
            self.subjects.set_data([], message=msg)
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            for k in ("Graded", "Average", "Strongest", "Trend"):
                self._stat(k, "–")
            return

        values = [s.value for _, s, _ in scored]
        if pct:
            lo, hi = 0.0, 100.0
            ticks = [(v, f"{v}%") for v in (0, 25, 50, 75, 100)]
            fmt = lambda v: f"{v:.0f}%"
        else:
            lo, hi = math.floor(min(values)) - 0.5, math.ceil(max(values)) + 0.5
            if hi - lo < 2:
                lo, hi = lo - 1, hi + 1
            step = max(0.5, round((hi - lo) / 5 * 2) / 2)
            ticks, v0 = [], math.ceil(lo / step) * step
            while v0 <= hi:
                ticks.append((v0, f"{v0:.1f}"))
                v0 += step
            fmt = lambda v: f"{v:.1f}"

        series, by_subject = [], {}
        for subj in subjects:
            mine = sorted(((t, s, due) for t, s, due in scored if (t.get("subject") or "Unknown") == subj), key=lambda x: x[2])
            if not mine:
                continue
            by_subject[subj] = mine
            pts = [((i + 1) if by_index else due, s.value, s.label, t.get("id"), t.get("name"), due) for i, (t, s, due) in enumerate(mine)]
            series.append({"name": subj, "color": color_of[subj], "points": pts})
        self.trend.set_data(series, lo, hi, ticks, by_index=by_index)

        rows = []
        for subj, mine in by_subject.items():
            vals = [s.value for _, s, _ in mine]
            a = sum(vals) / len(vals)
            rows.append((subj, a, fmt(a), color_of[subj], f"{subj}: {len(vals)} mark{'s' * (len(vals) != 1)}, average {fmt(a)}"))
        rows.sort(key=lambda r: -r[1])
        self.subjects.set_data(rows, lo, hi)
        self._fill_table(by_subject, fmt, pct)

        avg = sum(values) / len(values)
        self._stat("Graded", str(len(scored)), f"{kind} marked")
        self._stat("Average", fmt(avg), f"Average {what}" if not pct else f"Average {what} %")
        best = rows[0]
        self._stat("Strongest", _short(best[0], 18), f"Strongest subject · {best[2]}")
        ordered = sorted(scored, key=lambda x: x[2])
        if len(ordered) >= 4:
            n = max(2, len(ordered) // 3)
            first = sum(s.value for _, s, _ in ordered[:n]) / n
            last = sum(s.value for _, s, _ in ordered[-n:]) / n
            diff = last - first
            band = 0.05 * (hi - lo)
            arrow = "↑" if diff > band else "↓" if diff < -band else "→"
            self._stat("Trend", f"{arrow} {abs(diff):.1f}{'%' if pct else ''}", f"Trend: average of latest {n} vs first {n}")
        else:
            self._stat("Trend", "–", "Trend (needs 4+ marks)")

    def _fill_table(self, by_subject: dict, fmt, pct: bool):
        """One row per subject, one column per task in due-date order, then the average (like an achievement sheet)."""
        n = max(len(v) for v in by_subject.values())
        dark = QColor(self.c["window"]).lightness() < 128
        self.table.clear()
        self.table.setColumnCount(n + 2)
        self.table.setRowCount(len(by_subject))
        self.table.setHorizontalHeaderLabels(["Subject"] + [f"Task {i + 1}" for i in range(n)] + ["Average"])
        bold = self.table.font()
        bold.setBold(True)
        for r, (subj, mine) in enumerate(by_subject.items()):
            name = QTableWidgetItem(subj)
            name.setToolTip(subj)
            self.table.setItem(r, 0, name)
            for i, (t, s, due) in enumerate(mine):
                cell = QTableWidgetItem(fmt(s.value))
                cell.setTextAlignment(Qt.AlignCenter)
                cell.setData(TASK_ROLE, t.get("id"))
                level = insights.task_level(t)
                cell.setToolTip(f"{t.get('name')}\nDue {due:%d %b %Y}" + (f"\n{level} level" if level else ""))
                if level:
                    cell.setBackground(QBrush(QColor(LEVEL_COLORS[level][dark])))
                    cell.setForeground(QBrush(QColor("#f4f4f5" if dark else "#18181b")))
                self.table.setItem(r, i + 1, cell)
            vals = [s.value for _, s, _ in mine]
            avg = QTableWidgetItem(fmt(sum(vals) / len(vals)))
            avg.setTextAlignment(Qt.AlignCenter)
            avg.setFont(bold)
            self.table.setItem(r, n + 1, avg)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, n + 2):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)

    def _cell_open(self, row, col):
        it = self.table.item(row, col)
        tid = it.data(TASK_ROLE) if it else None
        if tid is not None:
            self.open_task.emit(tid)

    def _stat(self, key, value, sub=None):
        num, lab = self.stats[key]
        f = num.font()
        f.setPointSize(self.font().pointSize() + (6 if len(value) <= 12 else 2))
        num.setFont(f)
        num.setText(value)
        num.setToolTip(value)
        if sub:
            lab.setText(sub)


def _short(s: str, n: int = 22) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
