"""Small hand-drawn charts (QPainter) that follow the app theme: a timeline chart and a bar chart."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

# Categorical hues in fixed order (validated light / dark steps). Subjects past the 8th fold to grey.
SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]


def series_colors(c: dict) -> list[str]:
    return SERIES_DARK if QColor(c["window"]).lightness() < 128 else SERIES_LIGHT


class _Base(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.c: dict = {}
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.message = ""

    def set_colors(self, c: dict):
        self.c = c
        self.update()

    def _font(self, delta=0, bold=False) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(max(6.0, f.pointSizeF() + delta))
        f.setBold(bold)
        return f

    def _empty(self, p: QPainter) -> bool:
        if self.message:
            p.setPen(QColor(self.c.get("muted", "#888")))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            return True
        return False


class TimelineChart(_Base):
    """Results over the year: one line per subject, x = due date, y = score."""
    point_clicked = Signal(object)   # task id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series: list[dict] = []     # {name, color, points: [(datetime, y, label, task_id, task_name)]}
        self.lo, self.hi = 0.0, 100.0
        self.ticks: list[tuple[float, str]] = []
        self.hidden: set[str] = set()
        self.by_index = False
        self._hit: list[tuple[QPointF, dict, tuple]] = []
        self._legend: list[tuple[QRectF, str]] = []
        self._hover = None
        self.setMinimumHeight(220)

    def set_data(self, series, lo, hi, ticks, message="", by_index=False):
        """Points are (x, y, label, task_id, task_name, due). x is a datetime, or 1, 2, 3… when by_index."""
        self.series, self.lo, self.hi, self.ticks, self.message = series, lo, hi, ticks, message
        self.by_index = by_index
        self.hidden &= {s["name"] for s in series}
        self._hover = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.c
        if self._empty(p):
            return
        text, muted, grid = QColor(c["text"]), QColor(c["muted"]), QColor(c["line"])
        fm = p.fontMetrics()

        # legend (click to show / hide a subject)
        self._legend = []
        x, y = 4.0, 4.0
        p.setFont(self._font(-1))
        fm = p.fontMetrics()
        for s in self.series:
            w = 18 + fm.horizontalAdvance(s["name"]) + 16
            if x + w > self.width() and x > 4:
                x, y = 4.0, y + fm.height() + 6
            r = QRectF(x, y, w, fm.height() + 2)
            off = s["name"] in self.hidden
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(s["color"]) if not off else Qt.NoBrush)
            if off:
                p.setPen(QPen(QColor(s["color"]), 1.5))
            p.drawRoundedRect(QRectF(x + 2, y + fm.height() / 2 - 4, 10, 10), 3, 3)
            p.setPen(muted if off else text)
            p.drawText(QRectF(x + 18, y, w - 18, fm.height() + 2), Qt.AlignVCenter, s["name"])
            self._legend.append((r, s["name"]))
            x += w
        top = y + fm.height() + 14

        visible = [s for s in self.series if s["name"] not in self.hidden]
        pts = [pt for s in visible for pt in s["points"]]
        all_pts = [pt for s in self.series for pt in s["points"]]
        if not all_pts:
            return
        if self.by_index:
            x0, x1 = 0.5, max(pt[0] for pt in all_pts) + 0.5
        else:
            x0 = min(pt[0] for pt in all_pts) - timedelta(days=7)
            x1 = max(pt[0] for pt in all_pts) + timedelta(days=7)
        left = 12 + max([fm.horizontalAdvance(lbl) for _, lbl in self.ticks] + [20])
        plot = QRectF(left, top, self.width() - left - 16, self.height() - top - fm.height() - 14)
        if plot.width() < 40 or plot.height() < 40:
            return
        span = (x1 - x0) if self.by_index else ((x1 - x0).total_seconds() or 1)

        def X(d) -> float:
            off = (d - x0) if self.by_index else (d - x0).total_seconds()
            return plot.left() + off / span * plot.width()

        def Y(v: float) -> float:
            return plot.bottom() - (v - self.lo) / ((self.hi - self.lo) or 1) * plot.height()

        # grid + y labels
        for v, lbl in self.ticks:
            yy = Y(v)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(plot.left(), yy), QPointF(plot.right(), yy))
            p.setPen(muted)
            p.drawText(QRectF(0, yy - fm.height() / 2, left - 8, fm.height()), Qt.AlignRight | Qt.AlignVCenter, lbl)
        if self.by_index:
            n = int(x1 - 0.5)
            wide = plot.width() / max(n, 1) > 56
            for i in range(1, n + 1):
                xx = X(i)
                p.setPen(QPen(grid, 1, Qt.DotLine))
                p.drawLine(QPointF(xx, plot.top()), QPointF(xx, plot.bottom()))
                p.setPen(muted)
                p.drawText(QRectF(xx - 30, plot.bottom() + 4, 60, fm.height()), Qt.AlignHCenter, f"Task {i}" if wide else str(i))
        # month labels
        d = datetime(x0.year, x0.month, 1, tzinfo=x0.tzinfo) if not self.by_index else None
        months = (x1.year - x0.year) * 12 + x1.month - x0.month + 1 if d else 0
        step = max(1, math.ceil(months / max(1.0, plot.width() / 60)))
        i = 0
        while d is not None and d <= x1:
            if d >= x0 and i % step == 0:
                xx = X(d)
                p.setPen(QPen(grid, 1, Qt.DotLine))
                p.drawLine(QPointF(xx, plot.top()), QPointF(xx, plot.bottom()))
                p.setPen(muted)
                p.drawText(QRectF(xx - 30, plot.bottom() + 4, 60, fm.height()), Qt.AlignHCenter, d.strftime("%b" if d.month != 1 else "%b %y"))
            d = datetime(d.year + (d.month == 12), d.month % 12 + 1, 1, tzinfo=d.tzinfo)
            i += 1
        p.setPen(QPen(grid, 1))
        p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))

        # series
        self._hit = []
        surface = QColor(c["base"])
        for s in visible:
            col = QColor(s["color"])
            ordered = sorted(s["points"], key=lambda pt: pt[0])
            if len(ordered) > 1:
                path = QPainterPath(QPointF(X(ordered[0][0]), Y(ordered[0][1])))
                for pt in ordered[1:]:
                    path.lineTo(QPointF(X(pt[0]), Y(pt[1])))
                p.setPen(QPen(col, 2))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            for pt in ordered:
                q = QPointF(X(pt[0]), Y(pt[1]))
                hover = self._hover is not None and self._hover[2] is pt
                p.setPen(QPen(surface, 2))
                p.setBrush(col)
                p.drawEllipse(q, 6 if hover else 4.5, 6 if hover else 4.5)
                self._hit.append((q, s, pt))
        if not pts:
            p.setPen(muted)
            p.drawText(plot, Qt.AlignCenter, "All subjects hidden. Click a subject above to show it.")

    def _nearest(self, pos):
        best, dist = None, 14 ** 2
        for q, s, pt in self._hit:
            d = (q.x() - pos.x()) ** 2 + (q.y() - pos.y()) ** 2
            if d < dist:
                best, dist = (q, s, pt), d
        return best

    def mouseMoveEvent(self, e):
        hit = self._nearest(e.position())
        if (hit and hit[2]) != (self._hover and self._hover[2]):
            self._hover = hit
            self.update()
        if hit:
            _, s, pt = hit
            QToolTip.showText(e.globalPosition().toPoint(), f"<b>{pt[4]}</b><br>{s['name']}<br>{pt[2]}  ·  due {pt[5]:%d %b %Y}", self)
            self.setCursor(Qt.PointingHandCursor)
        else:
            QToolTip.hideText()
            on_legend = any(r.contains(e.position()) for r, _ in self._legend)
            self.setCursor(Qt.PointingHandCursor if on_legend else Qt.ArrowCursor)

    def leaveEvent(self, _):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        for r, name in self._legend:
            if r.contains(e.position()):
                self.hidden.symmetric_difference_update({name})
                self.update()
                return
        hit = self._nearest(e.position())
        if hit:
            self.point_clicked.emit(hit[2][3])


class BarChart(_Base):
    """Horizontal bars: rows of (label, value, value text, colour, tooltip)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[tuple] = []
        self.lo, self.hi = 0.0, 100.0
        self._hit: list[tuple[QRectF, tuple]] = []
        self.fixed_row = 0
        self.setMinimumHeight(140)

    def set_data(self, rows, lo=0.0, hi=100.0, message=""):
        self.rows, self.lo, self.hi, self.message = rows, lo, hi, message
        if self.fixed_row:   # inside a scroll area: grow to fit every row instead of squeezing them
            self.setMinimumHeight(int(len(rows) * self.fixed_row + 6) if rows else 60)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._empty(p) or not self.rows:
            return
        c = self.c
        fm = p.fontMetrics()
        label_w = min(self.width() * 0.55, max(fm.horizontalAdvance(r[0]) for r in self.rows) + 12)
        value_w = max(fm.horizontalAdvance(r[2]) for r in self.rows) + 12
        avail = self.width() - label_w - value_w - 8
        row_h = self.fixed_row or max(fm.height() + 8, min(30, (self.height() - 4) / len(self.rows)))
        bar_h = min(14, row_h - 8)
        self._hit = []
        for i, row in enumerate(self.rows):
            label, value, vtext, color = row[:4]
            y = 2 + i * row_h
            p.setPen(QColor(c["text"]))
            p.drawText(QRectF(0, y, label_w - 10, row_h), Qt.AlignVCenter | Qt.AlignRight,
                       fm.elidedText(label, Qt.ElideRight, int(label_w - 10)))
            frac = max(0.0, min(1.0, (value - self.lo) / ((self.hi - self.lo) or 1)))
            track = QRectF(label_w, y + (row_h - bar_h) / 2, avail, bar_h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["alt"]))
            p.drawRoundedRect(track, 4, 4)
            bar = QRectF(track.left(), track.top(), max(bar_h, avail * frac), bar_h)
            p.setBrush(QColor(color))
            p.drawRoundedRect(bar, 4, 4)
            p.setPen(QColor(c["text"]))
            p.drawText(QRectF(track.right() + 8, y, value_w, row_h), Qt.AlignVCenter | Qt.AlignLeft, vtext)
            self._hit.append((QRectF(0, y, self.width(), row_h), row))

    def mouseMoveEvent(self, e):
        for r, row in self._hit:
            if r.contains(e.position()):
                if len(row) > 4 and row[4]:
                    QToolTip.showText(e.globalPosition().toPoint(), row[4], self)
                return
        QToolTip.hideText()
