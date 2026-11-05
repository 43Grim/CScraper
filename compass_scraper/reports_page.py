"""The Reports page: Victorian Curriculum levels, learning behaviours, attendance and teachers,
read from the "All Semester Reports" ZIP you download from Compass."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import theme
from .charts import BarChart, TimelineChart, series_colors
from .performance import LEVEL_COLORS, _card, _scrolling
from .reports import BEHAVIOURS, RATINGS, ReportStore, latest_ratings, rating_value

# Ratings use the same colours as the expected-level key on the Performance page.
RATING_LEVEL = {"Needs Attention": "Below", "Inconsistent": "Towards", "Good": "At", "Very Good": "Above",
                "Excellent": "Well above"}
SHORT_BEHAVIOUR = {"Agency in learning": "Agency", "Completes required work": "Completes work",
                   "Works productively": "Productive", "Seeks assistance when necessary": "Seeks help",
                   "Works in a team": "Teamwork", "Respects the rights of others to learn": "Respects others"}


def level_text(level: float | None, beyond: float | None = None) -> str:
    if level is None:
        return "–"
    if beyond and level >= beyond:
        return f"Beyond {int(beyond) - 1}"
    return f"{level:.1f}"


def level_vs_expected(level: float | None, expected) -> str | None:
    """Where a level sits against the yellow expected band: Below, At, Above or Well above."""
    if level is None or not expected:
        return None
    lo, hi = expected
    if level < lo:
        return "Below" if level < lo - 0.5 else "Towards"
    if level <= hi:
        return "At"
    return "Well above" if level >= hi + 1 else "Above"


class GuideDialog(QDialog):
    """The Learning Behaviour Data table, as saved from the reports."""

    def __init__(self, image: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Learning behaviour guide")
        self.resize(900, 640)
        v = QVBoxLayout(self)
        pic = QLabel()
        pic.setAlignment(Qt.AlignCenter)
        pix = QPixmap(str(image))
        pic.setPixmap(pix)
        scroll = QScrollArea()
        scroll.setWidget(pic)
        scroll.setWidgetResizable(True)
        v.addWidget(scroll, 1)
        row = QHBoxLayout()
        note = QLabel("From your school reports. What each learning behaviour rating means.")
        note.setObjectName("muted")
        row.addWidget(note, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)


class ReportsPage(QWidget):
    CURRICULUM, SUBJECTS = "curriculum", "subjects"

    def __init__(self, settings: QSettings | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.store = ReportStore(None)
        self.c: dict = {}
        self.job = None
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel("Reports")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        top.addSpacing(16)
        self.view = theme.Segmented()
        self.view.set_options(((self.CURRICULUM, "Curriculum levels"), (self.SUBJECTS, "Subjects")))
        self.view.changed.connect(self._view_changed)
        top.addWidget(self.view)
        self.report = theme.Combo()
        self.report.setToolTip("Which report to show")
        self.report.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.report.currentIndexChanged.connect(self._fill_subjects)
        top.addWidget(self.report)
        top.addStretch(1)
        self.guide_btn = QPushButton("Behaviour guide")
        self.guide_btn.setToolTip("What each learning behaviour rating means (the table from your reports)")
        self.guide_btn.clicked.connect(self.show_guide)
        top.addWidget(self.guide_btn)
        self.import_btn = QPushButton("Import reports ZIP…")
        self.import_btn.setObjectName("primary")
        self.import_btn.setToolTip("Choose the ZIP from Compass: Reports → Download All Semester Reports")
        self.import_btn.clicked.connect(self.choose_file)
        top.addWidget(self.import_btn)
        v.addLayout(top)

        self.info = QLabel()
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        v.addWidget(self.info)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        # empty state
        empty = QFrame()
        empty.setObjectName("card")
        ev = QVBoxLayout(empty)
        ev.setContentsMargins(28, 24, 28, 24)
        head = QLabel("Import your school reports")
        head.setObjectName("sectionTitle")
        ev.addWidget(head)
        steps = QLabel(
            "1. In Compass, open your profile and go to the <b>Reports</b> tab.<br>"
            "2. Click <b>Download All Semester Reports</b>. Compass gives you a ZIP of PDFs.<br>"
            "3. Click <b>Import reports ZIP…</b> and choose that ZIP.<br><br>"
            "Only your Victorian Curriculum levels, learning behaviours, class attendance and teachers are kept. "
            "Teacher comments and everything else in the reports are ignored. "
            "The data is saved in your portfolio folder (reports.json), so you don't need to keep the ZIP.")
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        ev.addWidget(steps)
        ev.addStretch(1)
        self.stack.addWidget(empty)

        # curriculum view
        cur = QWidget()
        cg = QGridLayout(cur)
        cg.setContentsMargins(0, 0, 0, 0)
        cg.setSpacing(12)
        card, cv = _card("Victorian Curriculum levels",
                         "Your level in each strand at every semester report, coloured against the expected level "
                         "(the yellow band on the report). 7.0 is the start of Level 7 and 7.5 is halfway through it.")
        self.levels = QTableWidget()
        self.levels.setEditTriggers(QTableWidget.NoEditTriggers)
        self.levels.setSelectionMode(QTableWidget.NoSelection)
        self.levels.verticalHeader().setVisible(False)
        cv.addWidget(self.levels, 1)
        self.key = QHBoxLayout()
        self.key_labels: dict[str, QLabel] = {}
        k = QLabel("Key")
        k.setObjectName("muted")
        self.key.addWidget(k)
        for name, text in (("Below", "Below expected"), ("Towards", "Just below"), ("At", "At expected"),
                           ("Above", "Above"), ("Well above", "A level or more above")):
            lab = QLabel(text)
            lab.setAlignment(Qt.AlignCenter)
            self.key_labels[name] = lab
            self.key.addWidget(lab, 1)
        cv.addLayout(self.key)
        cg.addWidget(card, 0, 0)
        card, cv = _card("Levels over time", "Average level of each learning area. Click a name to show or hide it.")
        self.level_chart = TimelineChart()
        cv.addWidget(self.level_chart, 1)
        cg.addWidget(card, 1, 0)
        cg.setRowStretch(0, 3)
        cg.setRowStretch(1, 2)
        self.stack.addWidget(cur)

        # subjects view
        sub = QWidget()
        sg = QGridLayout(sub)
        sg.setContentsMargins(0, 0, 0, 0)
        sg.setSpacing(12)
        card, cv = _card("Subjects", "Teacher, class attendance and learning behaviours in the report's latest term. "
                                     "Hover a rating to see every term.")
        self.subjects = QTableWidget()
        self.subjects.setEditTriggers(QTableWidget.NoEditTriggers)
        self.subjects.setSelectionMode(QTableWidget.NoSelection)
        self.subjects.verticalHeader().setVisible(False)
        cv.addWidget(self.subjects, 1)
        self.rating_key = QHBoxLayout()
        self.rating_labels: dict[str, QLabel] = {}
        for r in RATINGS:
            lab = QLabel(r)
            lab.setAlignment(Qt.AlignCenter)
            self.rating_labels[r] = lab
            self.rating_key.addWidget(lab, 1)
        cv.addLayout(self.rating_key)
        sg.addWidget(card, 0, 0, 1, 2)
        card, cv = _card("Learning behaviours over time", "Average rating across your subjects at each report.")
        self.behaviour_chart = TimelineChart()
        cv.addWidget(self.behaviour_chart, 1)
        sg.addWidget(card, 1, 0)
        card, cv = _card("Class attendance", "In this report, by subject.")
        self.attendance = BarChart()
        self.attendance.fixed_row = 26
        cv.addWidget(_scrolling(self.attendance), 1)
        sg.addWidget(card, 1, 1)
        sg.setColumnStretch(0, 3)
        sg.setColumnStretch(1, 2)
        sg.setRowStretch(0, 3)
        sg.setRowStretch(1, 2)
        self.stack.addWidget(sub)
        self._refresh_all()

    # ── data ─────────────────────────────────────────────────────────
    def set_root(self, root: Path | None):
        self.store = ReportStore.load(root)
        self._refresh_all()

    def set_colors(self, c: dict):
        self.c = c
        for ch in (self.level_chart, self.behaviour_chart, self.attendance):
            ch.set_colors(c)
        dark = self._dark()
        style = lambda level: (f"background:{LEVEL_COLORS[level][dark]}; color:{'#f4f4f5' if dark else '#18181b'};"
                               " border-radius:4px; padding:3px 6px;")
        for name, lab in self.key_labels.items():
            lab.setStyleSheet(style(name))
        for name, lab in self.rating_labels.items():
            lab.setStyleSheet(style(RATING_LEVEL[name]))
        self._refresh_all()

    def _dark(self) -> bool:
        return bool(self.c) and QColor(self.c["window"]).lightness() < 128

    def choose_file(self):
        if not self.store.root:
            QMessageBox.information(self, "Reports", "Choose a portfolio folder on the Sync page first. "
                                                     "The report data is saved there.")
            return
        start = str(Path.home() / "Downloads")
        path, _ = QFileDialog.getOpenFileName(self, "Import Compass reports", start,
                                              "Compass reports (*.zip *.pdf);;All files (*)")
        if path:
            self.import_file(path)

    def import_file(self, path: str):
        from .gui import start_job    # avoids a circular import

        self.import_btn.setEnabled(False)
        self.info.setText("Reading your reports…")

        def done(res):
            self.import_btn.setEnabled(True)
            read, skipped = res
            self.store = ReportStore.load(self.store.root)
            self._refresh_all()
            extra = f" ({skipped} other file{'s' * (skipped != 1)} skipped)" if skipped else ""
            self.info.setText(f"Imported {read} report{'s' * (read != 1)}{extra}. " + self._summary())

        def fail(kind, msg):
            self.import_btn.setEnabled(True)
            self._refresh_all()
            msg = msg.split(": ", 1)[1] if msg.startswith("ReportError: ") else msg
            QMessageBox.warning(self, "Couldn't import reports", msg)

        store = ReportStore.load(self.store.root)   # a fresh copy for the worker thread
        self.job = start_job(self, lambda job: store.import_zip(path, job.log.emit), done, fail)

    def show_guide(self):
        if self.store.guide:
            GuideDialog(self.store.guide, self).exec()

    # ── views ────────────────────────────────────────────────────────
    def _summary(self) -> str:
        reps = self.store.reports
        if not reps:
            return ""
        years = sorted({r.year for r in reps})
        span = f"{years[0]} to {years[-1]}" if len(years) > 1 else str(years[0])
        return f"{len(reps)} reports from {span}, saved in your portfolio folder."

    def _refresh_all(self):
        has = bool(self.store.reports)
        self.view.setVisible(has)
        self.guide_btn.setVisible(self.store.guide is not None)
        self.import_btn.setText("Import again…" if has else "Import reports ZIP…")
        self.info.setText(self._summary() if has else "")
        keep = self.report.currentData()
        self.report.blockSignals(True)
        self.report.clear()
        for r in reversed([r for r in self.store.reports if r.subjects]):
            self.report.addItem(f"{r.period} {r.year}" + (" (learning behaviours)" if r.kind != "semester" else ""), r.cycle)
        i = self.report.findData(keep)
        self.report.setCurrentIndex(i if i >= 0 else 0)
        self.report.blockSignals(False)
        if not has:
            self.report.setVisible(False)
            self.stack.setCurrentIndex(0)
            return
        self._fill_curriculum()
        self._fill_subjects()
        self._fill_behaviour_chart()
        self._view_changed(self.view.current())

    def _view_changed(self, view: str):
        if not self.store.reports:
            return
        self.stack.setCurrentIndex(1 if view == self.CURRICULUM else 2)
        self.report.setVisible(view == self.SUBJECTS)

    def _fill_curriculum(self):
        sems = self.store.semester_reports()
        strands = self.store.strands()
        dark = self._dark()
        t = self.levels
        t.clear()
        t.setRowCount(len(strands))
        t.setColumnCount(len(sems) + 2)
        t.setHorizontalHeaderLabels(["Learning area", "Strand"] + [f"{r.period.replace('Semester', 'Sem')}\n{r.year}" for r in sems])
        prev = None
        for row, (area, strand) in enumerate(strands):
            a = QTableWidgetItem(area if area != prev else "")
            a.setToolTip(area)
            prev = area
            t.setItem(row, 0, a)
            name = QTableWidgetItem(strand)
            name.setToolTip(f"{area} · {strand}" if area and area != strand else strand)
            t.setItem(row, 1, name)
            for col, rep in enumerate(sems, 2):
                entry = next((c for c in rep.curriculum if (c["area"], c["strand"]) == (area, strand)), None)
                if not entry:
                    continue
                cell = QTableWidgetItem(level_text(entry["level"], entry.get("beyond")))
                cell.setTextAlignment(Qt.AlignCenter)
                exp = entry.get("expected")
                where = level_vs_expected(entry["level"], exp)
                tip = f"{area} · {strand}\n{rep.period} {rep.year} ({rep.year_level})\nLevel {level_text(entry['level'], entry.get('beyond'))}"
                if exp:
                    tip += f"\nExpected {exp[0]:.1f} to {exp[1]:.1f}"
                cell.setToolTip(tip)
                if where and self.c:
                    cell.setBackground(QBrush(QColor(LEVEL_COLORS[where][dark])))
                    cell.setForeground(QBrush(QColor("#f4f4f5" if dark else "#18181b")))
                t.setItem(row, col, cell)
        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        for i in range(2, len(sems) + 2):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        # chart: average level per learning area, plus the expected level
        if not self.c:
            return
        palette = series_colors(self.c)
        areas = list(dict.fromkeys(a for a, _ in strands))
        palette = palette[:8] if len(areas) <= 8 else palette   # past 8 areas, the rest fold to grey
        series = []
        labels = [r.short for r in sems]
        for i, area in enumerate(areas):
            pts = []
            for x, rep in enumerate(sems, 1):
                vals = [c["level"] for c in rep.curriculum if c["area"] == area and c["level"] is not None]
                if vals:
                    avg = sum(vals) / len(vals)
                    pts.append((x, avg, f"Average level {avg:.1f}", None, area, f"{rep.period} {rep.year}"))
            if pts:
                series.append({"name": area, "color": palette[i] if i < len(palette) else self.c["muted"], "points": pts})
        exp = []
        for x, rep in enumerate(sems, 1):
            bands = [c["expected"] for c in rep.curriculum if c.get("expected")]
            if bands:
                hi = max(b[1] for b in bands)
                exp.append((x, hi, f"Expected up to {hi:.1f}", None, "Expected level", f"{rep.period} {rep.year}"))
        if exp:
            series.append({"name": "Expected", "color": self.c["text"], "points": exp, "dashed": True})
        allv = [p[1] for s in series for p in s["points"]]
        if not allv:
            self.level_chart.set_data([], 0, 1, [], "No Victorian Curriculum levels in these reports.")
            return
        lo, hi = int(min(allv)) - 0.5, int(max(allv)) + 1.5
        ticks = [(v, f"{v:.0f}") for v in range(int(lo + 0.5), int(hi) + 1)]
        self.level_chart.set_data(series, lo, hi, ticks, by_index=True, x_labels=labels)

    def _current_report(self):
        cycle = self.report.currentData()
        return next((r for r in self.store.reports if r.cycle == cycle), None)

    def _fill_subjects(self):
        rep = self._current_report()
        t = self.subjects
        t.clear()
        if not rep:
            t.setRowCount(0)
            self.attendance.set_data([], message="No subjects in this report.")
            return
        names = [b for b in BEHAVIOURS if any(b in s.get("behaviours", {}) for s in rep.subjects)]
        names += [b for s in rep.subjects for b in s.get("behaviours", {}) if b not in names]
        dark = self._dark()
        t.setColumnCount(3 + len(names))
        t.setRowCount(len(rep.subjects))
        t.setHorizontalHeaderLabels(["Subject", "Teacher", "Attendance"] + [SHORT_BEHAVIOUR.get(n, n) for n in names])
        for i, n in enumerate(names):
            t.horizontalHeaderItem(3 + i).setToolTip(n)
        for row, s in enumerate(rep.subjects):
            t.setItem(row, 0, QTableWidgetItem(s["subject"]))
            t.setItem(row, 1, QTableWidgetItem(s.get("teacher") or ""))
            att = s.get("attendance")
            cell = QTableWidgetItem("–" if att is None else f"{att:g}%")
            cell.setTextAlignment(Qt.AlignCenter)
            t.setItem(row, 2, cell)
            latest = latest_ratings(s)
            for i, n in enumerate(names):
                rating = latest.get(n)
                cell = QTableWidgetItem(rating or "–")
                cell.setTextAlignment(Qt.AlignCenter)
                terms = s.get("behaviours", {}).get(n, {})
                cell.setToolTip(n + "".join(f"\nTerm {k}: {v}" for k, v in sorted(terms.items())))
                if rating in RATING_LEVEL and self.c:
                    cell.setBackground(QBrush(QColor(LEVEL_COLORS[RATING_LEVEL[rating]][dark])))
                    cell.setForeground(QBrush(QColor("#f4f4f5" if dark else "#18181b")))
                t.setItem(row, 3 + i, cell)
        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 3 + len(names)):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeToContents)

        if self.c:
            rows = [(s["subject"], s["attendance"], f"{s['attendance']:g}%", self.c["accent"],
                     f"{s['subject']}: {s['attendance']:g}% attendance") for s in rep.subjects if s.get("attendance") is not None]
            rows.sort(key=lambda r: -r[1])
            self.attendance.set_data(rows, 0, 100, message="" if rows else "No attendance in this report.")

    def _fill_behaviour_chart(self):
        if not self.c:
            return
        reps = [r for r in self.store.reports if r.subjects]
        palette = series_colors(self.c)
        series = []
        for i, name in enumerate(self.store.behaviour_names()):
            pts = []
            for x, rep in enumerate(reps, 1):
                vals = [rating_value(latest_ratings(s).get(name)) for s in rep.subjects]
                vals = [v for v in vals if v]
                if vals:
                    avg = sum(vals) / len(vals)
                    word = RATINGS[round(avg) - 1]
                    pts.append((x, avg, f"Average {avg:.1f} (about {word}) across {len(vals)} subjects", None, name,
                                f"{rep.period} {rep.year}"))
            if pts:
                series.append({"name": SHORT_BEHAVIOUR.get(name, name), "color": palette[i % len(palette)], "points": pts})
        ticks = [(i + 1, r) for i, r in enumerate(RATINGS)]
        msg = "" if series else "No learning behaviour ratings in these reports."
        self.behaviour_chart.set_data(series, 0.5, 5.5, ticks, msg, by_index=True, x_labels=[r.short for r in reps])
