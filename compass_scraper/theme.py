"""Light / dark / system themes for the desktop app."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QStyledItemDelegate

# Neutral greys with a blue accent, in the style of current desktop apps.
LIGHT = {
    "window": "#f6f6f7", "base": "#ffffff", "alt": "#f4f4f5", "text": "#18181b", "muted": "#71717a",
    "line": "#e4e4e7", "sidebar": "#efeff1", "button": "#ffffff", "select": "#e4e4e7",
    "accent": "#2563eb", "accent_hover": "#1d4ed8", "accent_text": "#ffffff",
    "hit": "#dcfce7", "hit_text": "#14532d", "ok": "#15803d", "bad": "#dc2626",
}
DARK = {
    "window": "#1e1e20", "base": "#26262a", "alt": "#2c2c31", "text": "#e4e4e7", "muted": "#a1a1aa",
    "line": "#3a3a40", "sidebar": "#18181b", "button": "#2f2f35", "select": "#34343a",
    "accent": "#3b82f6", "accent_hover": "#60a5fa", "accent_text": "#ffffff",
    "hit": "#1f3b2b", "hit_text": "#bbf7d0", "ok": "#4ade80", "bad": "#f87171",
}


def system_is_dark(app: QApplication) -> bool:
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return app.palette().color(QPalette.Window).lightness() < 128


def colors_for(mode: str, app: QApplication) -> dict:
    dark = mode == "Dark" or (mode == "System" and system_is_dark(app))
    return DARK if dark else LIGHT


def _icon(name: str, svg: str) -> str:
    """Writes a small SVG once (stylesheets can only load icons from files) and returns its path."""
    folder = Path(tempfile.gettempdir()) / "compass-scraper-icons"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}-{hashlib.md5(svg.encode()).hexdigest()[:8]}.svg"
    if not path.exists():
        path.write_text(svg)
    return path.as_posix()


def _chevron(color: str, up: bool = False) -> str:
    d = "M3 7.5 L6 4.5 L9 7.5" if up else "M3 4.5 L6 7.5 L9 4.5"
    return _icon("chevron-up" if up else "chevron", f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                 f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _check(color: str) -> str:
    return _icon("check", f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                 f'<path d="M2.5 6.2 L5 8.6 L9.5 3.6" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>')


class Combo(QComboBox):
    """A dropdown whose popup follows the stylesheet.

    Qt's default combo popup delegate ignores ::item rules, which left hovered items
    unreadable in light mode. Dropdowns also get a compact width so long entries
    don't stretch the window. (This used to be an app-wide event filter, but a Python
    filter on every event crashes the embedded sign-in browser.)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(QStyledItemDelegate(self))
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)


def apply(app: QApplication, mode: str) -> dict:
    c = colors_for(mode, app)
    down, up, down_muted = _chevron(c["muted"]), _chevron(c["muted"], up=True), _chevron(c["line"])
    tick = _check(c["accent_text"])
    app.setStyle("Fusion")
    p = QPalette()
    roles = {
        QPalette.Window: c["window"], QPalette.WindowText: c["text"], QPalette.Base: c["base"],
        QPalette.AlternateBase: c["alt"], QPalette.Text: c["text"], QPalette.Button: c["button"],
        QPalette.ButtonText: c["text"], QPalette.ToolTipBase: c["base"], QPalette.ToolTipText: c["text"],
        QPalette.Highlight: c["accent"], QPalette.HighlightedText: c["accent_text"], QPalette.Link: c["accent"],
        QPalette.PlaceholderText: c["muted"], QPalette.Mid: c["muted"],
    }
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(c["muted"]))
    app.setPalette(p)
    app.setStyleSheet(f"""
        QWidget#sidebar {{ background: {c['sidebar']}; border-right: 1px solid {c['line']}; }}
        QLabel#appTitle {{ font-size: 16px; font-weight: 700; }}
        QLabel#muted {{ color: {c['muted']}; }}
        QLabel#pageTitle {{ font-size: 20px; font-weight: 700; }}
        QLabel#sectionTitle {{ font-weight: 600; }}
        QFrame#card {{ background: {c['base']}; border: 1px solid {c['line']}; border-radius: 8px; }}
        QPushButton {{ padding: 6px 14px; border-radius: 6px; border: 1px solid {c['line']}; background: {c['button']}; }}
        QPushButton:hover {{ background: {c['select']}; }}
        QPushButton:disabled {{ color: {c['muted']}; }}
        QPushButton#primary {{ background: {c['accent']}; color: {c['accent_text']}; border: 1px solid {c['accent']}; font-weight: 600; padding: 7px 18px; }}
        QPushButton#primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
        QPushButton#primary:disabled {{ background: {c['select']}; border-color: {c['line']}; color: {c['muted']}; }}
        QPushButton#danger:enabled {{ color: {c['bad']}; }}
        QPushButton#link {{ border: none; background: transparent; color: {c['accent']}; padding: 4px 4px; }}
        QPushButton#link:hover {{ text-decoration: underline; background: transparent; }}
        QListWidget#nav {{ background: transparent; border: none; font-size: 14px; outline: none; }}
        QListWidget#nav::item {{ padding: 8px 12px; border-radius: 6px; margin: 1px 0; color: {c['text']}; }}
        QListWidget#nav::item:hover {{ background: {c['select']}; }}
        QListWidget#nav::item:selected {{ background: {c['select']}; color: {c['text']}; font-weight: 600; }}
        QLineEdit, QPlainTextEdit, QTextBrowser, QTreeWidget, QListWidget {{
            border: 1px solid {c['line']}; border-radius: 6px; padding: 4px; background: {c['base']}; }}
        QLineEdit:focus {{ border-color: {c['accent']}; }}
        QLineEdit, QPlainTextEdit, QTextBrowser {{ color: {c['text']}; selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; }}

        /* dropdowns */
        QComboBox, QDateTimeEdit, QSpinBox {{
            background: {c['button']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 6px;
            padding: 0px 30px 0px 10px; min-height: 30px; max-height: 30px; }}
        QLineEdit {{ padding: 0px 8px; min-height: 30px; max-height: 30px; }}
        QComboBox:hover, QDateTimeEdit:hover, QSpinBox:hover {{ border-color: {c['muted']}; background: {c['alt']}; }}
        QComboBox:focus, QDateTimeEdit:focus, QSpinBox:focus {{ border-color: {c['accent']}; }}
        QComboBox:on {{ border-color: {c['accent']}; }}
        QComboBox:disabled {{ color: {c['muted']}; }}
        QComboBox:editable {{ background: {c['base']}; }}
        QComboBox::drop-down, QDateTimeEdit::drop-down {{
            subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; background: transparent; }}
        QComboBox::down-arrow, QDateTimeEdit::down-arrow {{ image: url({down}); width: 12px; height: 12px; }}
        QComboBox::down-arrow:on {{ image: url({up}); }}
        QComboBox::down-arrow:disabled {{ image: url({down_muted}); }}
        QComboBox QAbstractItemView {{
            background: {c['base']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 6px; padding: 4px;
            outline: none; selection-background-color: {c['select']}; selection-color: {c['text']}; }}
        QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; border-radius: 4px; color: {c['text']}; }}
        QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{
            background: {c['select']}; color: {c['text']}; }}
        QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 22px; border: none; background: transparent; }}
        QSpinBox::up-button {{ subcontrol-position: top right; }}
        QSpinBox::down-button {{ subcontrol-position: bottom right; }}
        QSpinBox::up-arrow {{ image: url({up}); width: 10px; height: 10px; }}
        QSpinBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
        QCalendarWidget QWidget {{ color: {c['text']}; alternate-background-color: {c['alt']}; }}
        QCalendarWidget QToolButton {{ color: {c['text']}; background: transparent; border: none; padding: 4px 8px; }}
        QCalendarWidget QToolButton:hover {{ background: {c['select']}; border-radius: 4px; }}
        QCalendarWidget QAbstractItemView {{ background: {c['base']}; selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; }}

        /* menus */
        QMenu {{ background: {c['base']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 6px; padding: 4px; }}
        QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
        QMenu::item:selected {{ background: {c['select']}; color: {c['text']}; }}
        QMenu::separator {{ height: 1px; background: {c['line']}; margin: 4px 6px; }}

        /* check boxes */
        QCheckBox {{ color: {c['text']}; spacing: 7px; }}
        QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {c['muted']}; border-radius: 4px; background: {c['base']}; }}
        QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
        QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({tick}); }}

        /* lists and tables: readable hover and selection in every theme */
        QTreeWidget, QListWidget, QTableWidget {{ color: {c['text']}; }}
        QTreeWidget::item:hover, QListWidget::item:hover, QTableWidget::item:hover {{ background: {c['alt']}; color: {c['text']}; }}
        QTableWidget {{ gridline-color: {c['line']}; border: 1px solid {c['line']}; border-radius: 6px; background: {c['base']}; }}
        QTableWidget::item:selected {{ background: {c['select']}; color: {c['text']}; }}
        QPushButton {{ color: {c['text']}; }}
        QListWidget#nav {{ border: none; }}
        QListWidget#feed {{ border: none; padding: 0; }}
        QListWidget#feed::item {{ padding: 7px 6px; border-bottom: 1px solid {c['line']}; }}
        QListWidget#feed::item:hover {{ background: {c['alt']}; }}
        QListWidget#feed::item:selected {{ background: {c['select']}; color: {c['text']}; }}
        QProgressBar {{ border: 1px solid {c['line']}; border-radius: 6px; text-align: center; background: {c['alt']}; height: 16px; }}
        QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
        QTreeWidget::item {{ padding: 4px 2px; }}
        QTreeWidget::item:selected, QTreeWidget::item:selected:hover {{ background: {c['accent']}; color: {c['accent_text']}; }}
        QHeaderView::section {{ background: {c['alt']}; border: none; border-bottom: 1px solid {c['line']}; padding: 5px; color: {c['muted']}; }}
        QSplitter::handle {{ background: transparent; width: 8px; }}
        QScrollArea#plain, QScrollArea#plain > QWidget > QWidget {{ background: transparent; border: none; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 3px; min-height: 28px; }}
        QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
        QScrollBar::handle:horizontal {{ background: {c['line']}; border-radius: 3px; min-width: 28px; }}
        QScrollBar::handle:horizontal:hover {{ background: {c['muted']}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        QToolTip {{ background: {c['base']}; color: {c['text']}; border: 1px solid {c['line']}; }}
    """)
    return c
