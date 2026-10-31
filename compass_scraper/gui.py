"""PySide6 desktop app:  compass-gui  (or  python -m compass_scraper.gui)."""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from . import __version__, changes, desktop, theme
from .auth import BROWSERS, diagnose, forget_session, load_session, save_session, session_from_browser, session_from_cookie_header
from .browse import BrowsePage
from .overview import Overview
from .performance import PerformancePage
from .quickfind import QuickFind
from .timeline import TimelinePage
from .client import CompassClient, Session, SessionExpired
from .scrape import Cancelled, Progress, run

DEFAULT_HOST = "auburnhs-vic.compass.education"
DEFAULT_OUT = Path.home() / "Documents" / "Compass Portfolio"


class Job(QThread):
    """Runs `fn(job)` off the UI thread; results come back through signals."""
    phase = Signal(str)
    log = Signal(str)
    files_total = Signal(int)
    file_done = Signal(str, bool, str)
    done = Signal(object)
    failed = Signal(str, str)   # kind, message

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.stop_requested = False

    def run(self):
        try:
            self.done.emit(self.fn(self))
        except Cancelled:
            self.failed.emit("cancelled", "Stopped. Files already downloaded are kept; sync again to resume.")
        except SessionExpired as e:
            self.failed.emit("session", str(e))
        except Exception as e:  # surfaced in the log
            self.failed.emit("error", f"{type(e).__name__}: {e}")


def start_job(parent, fn, on_done, on_fail=None) -> Job:
    job = Job(fn, parent)
    job.done.connect(on_done)
    if on_fail:
        job.failed.connect(on_fail)
    job.finished.connect(job.deleteLater)
    job.start()
    return job


def _fmt_secs(s: float) -> str:
    s = int(max(s, 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def _card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    v = QVBoxLayout(f)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(8)
    return f, v


# ── sign in ──────────────────────────────────────────────────────────
class SignInDialog(QDialog):
    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.session: Session | None = None
        self.job: Job | None = None
        self.setWindowTitle("Sign in to Compass")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.addWidget(_label("Sign in to Compass", "pageTitle"))
        v.addWidget(_label("1. Sign in to Compass in your normal browser, CAPTCHA and all.\n"
                           "2. Pick that browser below and click “Use my browser's session”.", "muted", wrap=True))
        form = QFormLayout()
        self.host = QLineEdit(settings.value("host", DEFAULT_HOST))
        self.browser = QComboBox()
        self.browser.addItems(["Auto"] + list(BROWSERS))
        self.browser.setCurrentText(settings.value("browser", "Auto"))
        form.addRow("School address", self.host)
        form.addRow("Browser", self.browser)
        v.addLayout(form)

        row = QHBoxLayout()
        open_btn = QPushButton("Open Compass (default browser)")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://{self.host_value()}/")))
        self.grab = QPushButton("Use my browser's session")
        self.grab.setObjectName("primary")
        self.grab.setDefault(True)
        self.grab.clicked.connect(self._grab)
        row.addWidget(open_btn)
        row.addStretch(1)
        row.addWidget(self.grab)
        v.addLayout(row)

        self.msg = QPlainTextEdit()
        self.msg.setReadOnly(True)
        self.msg.setMaximumHeight(130)
        self.msg.setPlaceholderText("Status messages appear here.")
        v.addWidget(self.msg)

        more = QHBoxLayout()
        paste = QPushButton("Paste cookie instead…")
        paste.setObjectName("link")
        paste.clicked.connect(self._paste)
        diag = QPushButton("Diagnose…")
        diag.setObjectName("link")
        diag.clicked.connect(self._diagnose)
        close = QPushButton("Cancel")
        close.clicked.connect(self.reject)
        more.addWidget(paste)
        more.addWidget(diag)
        more.addStretch(1)
        more.addWidget(close)
        v.addLayout(more)

    def host_value(self) -> str:
        return self.host.text().strip().replace("https://", "").replace("http://", "").split("/")[0] or DEFAULT_HOST

    def _say(self, text: str):
        self.msg.appendPlainText(text)

    def _busy(self, busy: bool):
        self.grab.setEnabled(not busy)

    def _accept_session(self, s: Session):
        self.settings.setValue("host", s.host)
        self.settings.setValue("browser", self.browser.currentText())
        self.session = s
        self.accept()

    def _grab(self):
        host, browser = self.host_value(), self.browser.currentText()
        self._say(f"Looking for a signed-in Compass session in {browser if browser != 'Auto' else 'your browsers'}…")
        self._busy(True)

        def grab(job):
            s = session_from_browser(host, browser=browser, log=job.log.emit)
            save_session(s)
            return s

        def fail(kind, msg):
            self._busy(False)
            self._say(msg)
            self._say("Tip: make sure you're signed in to Compass in that browser, pick it in the list, or use "
                      "“Diagnose…” and send the report.")
        self.job = start_job(self, grab, self._accept_session, fail)
        self.job.log.connect(self._say)

    def _paste(self):
        text, ok = QInputDialog.getMultiLineText(
            self, "Paste Compass cookie",
            "In your browser, open Compass, press F12 → Network, reload, click any request to\n"
            f"{self.host_value()} and copy the whole “Cookie” request header value here:")
        if not ok or not text.strip():
            return
        host = self.host_value()

        def make(_):
            s = session_from_cookie_header(host, text)
            save_session(s)
            return s
        self._busy(True)
        start_job(self, make, self._accept_session, lambda kind, msg: (self._busy(False), self._say(msg)))

    def _diagnose(self):
        host = self.host_value()
        self._say("Running diagnose…")

        def done(report):
            QApplication.clipboard().setText(report)
            self._say(report)
            self._say("\nThe report above is copied to your clipboard. It lists cookie names only, never values.")
        start_job(self, lambda _: diagnose(host), done, lambda kind, msg: self._say(msg))


# ── sync page ────────────────────────────────────────────────────────
class SyncPage(QWidget):
    synced = Signal(object)        # scrape.Result
    session_expired = Signal()
    years_loaded = Signal()

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.session: Session | None = None
        self.job: Job | None = None
        self.started = 0.0
        self.files_n = self.files_ok = self.files_failed = 0

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)
        v.addWidget(_label("Sync", "pageTitle"))
        v.addWidget(_label("Download your learning tasks, grades, feedback, rubrics and files from Compass. "
                           "Syncing again into the same folder only downloads what's new.", "muted", wrap=True))

        card, c = _card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        years_box = QVBoxLayout()
        years_box.addWidget(_label("Academic years"))
        self.years = QListWidget()
        self.years.setMinimumHeight(120)
        years_box.addWidget(self.years, 1)
        sel = QHBoxLayout()
        for label, state in (("All", Qt.Checked), ("None", Qt.Unchecked)):
            b = QPushButton(label)
            b.setObjectName("link")
            b.clicked.connect(lambda _=False, s=state: [self.years.item(i).setCheckState(s) for i in range(self.years.count())])
            sel.addWidget(b)
        sel.addStretch(1)
        years_box.addLayout(sel)
        grid.addLayout(years_box, 0, 0)

        opts = QFormLayout()
        opts.setHorizontalSpacing(14)
        opts.setVerticalSpacing(8)
        opts.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.dl_files = QCheckBox("Download attachments, submissions and teacher responses")
        self.dl_files.setChecked(settings.value("download", True, type=bool))
        self.make_zip = QCheckBox("Also build a ZIP of everything")
        self.make_zip.setChecked(settings.value("zip", True, type=bool))
        self.hidden = QCheckBox("Include tasks Compass marks as hidden")
        self.hidden.setChecked(settings.value("hidden", False, type=bool))
        self.autosync = QCheckBox("Sync automatically when the app opens")
        self.autosync.setChecked(settings.value("autosync", False, type=bool))
        self.autosync.toggled.connect(lambda on: settings.setValue("autosync", on))
        self.workers = QSpinBox()
        self.workers.setRange(1, 8)
        self.workers.setValue(settings.value("workers", 4, type=int))
        out_row = QHBoxLayout()
        self.out = QLineEdit(settings.value("out", str(DEFAULT_OUT)))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        out_row.addWidget(self.out, 1)
        out_row.addWidget(browse)
        opts.addRow(self.dl_files)
        opts.addRow(self.make_zip)
        opts.addRow(self.hidden)
        opts.addRow(self.autosync)
        self.workers.setFixedWidth(110)
        opts.addRow("Parallel downloads", self.workers)
        opts.addRow("Save to", out_row)
        grid.addLayout(opts, 0, 1)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        c.addLayout(grid)
        v.addWidget(card)

        prog, p = _card()
        btns = QHBoxLayout()
        self.start_btn = QPushButton("Sync now")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.phase = _label("Ready.")
        f = self.phase.font()
        f.setBold(True)
        self.phase.setFont(f)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addSpacing(10)
        btns.addWidget(self.phase, 1)
        p.addLayout(btns)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        p.addWidget(self.bar)
        self.stats = _label("", "muted")
        p.addWidget(self.stats)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("monospace", 9))
        p.addWidget(self.log, 1)
        v.addWidget(prog, 1)

        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self._tick)
        self.set_session(None)

    # state
    def set_session(self, session: Session | None):
        self.session = session
        self.years.clear()
        self.start_btn.setEnabled(session is not None and self.job is None)
        if session:
            self._load_years()
        else:
            self.phase.setText("Sign in to Compass to sync.")

    def say(self, msg: str):
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {msg}")

    def _load_years(self):
        session = self.session
        unticked = set(self.settings.value("unticked_years", [], type=list) or [])

        def fill(groups):
            self.years.clear()
            for g in sorted(groups, key=lambda g: str(g.get("importIdentifier") or g.get("name")), reverse=True):
                it = QListWidgetItem(str(g.get("name")))
                it.setData(Qt.UserRole, str(g.get("id")))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked if str(g.get("id")) in unticked else Qt.Checked)
                self.years.addItem(it)
            self.phase.setText("Ready.")
            self.years_loaded.emit()
        start_job(self, lambda _: CompassClient(session).academic_groups(), fill, lambda kind, msg: self.say(msg))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save portfolio to", str(Path(self.out.text()).expanduser().parent))
        if d:
            self.out.setText(d)

    def _save_settings(self):
        s = self.settings
        s.setValue("download", self.dl_files.isChecked())
        s.setValue("zip", self.make_zip.isChecked())
        s.setValue("hidden", self.hidden.isChecked())
        s.setValue("workers", self.workers.value())
        s.setValue("out", self.out.text())
        s.setValue("unticked_years", [self.years.item(i).data(Qt.UserRole) for i in range(self.years.count())
                                      if self.years.item(i).checkState() != Qt.Checked])

    # run
    def start(self):
        years = [self.years.item(i).data(Qt.UserRole) for i in range(self.years.count()) if self.years.item(i).checkState() == Qt.Checked]
        if self.years.count() and not years:
            QMessageBox.information(self, "No years selected", "Tick at least one academic year.")
            return
        self._save_settings()
        out = Path(self.out.text()).expanduser()
        client = CompassClient(self.session)
        opts = dict(years=years or None, download=self.dl_files.isChecked(), zip_output=self.make_zip.isChecked(),
                    include_hidden=self.hidden.isChecked(), workers=self.workers.value())
        self.files_n = self.files_ok = self.files_failed = 0
        self.bar.setRange(0, 0)
        self.started = time.time()
        self.ticker.start(1000)
        self.say(f"Syncing to {out}")

        def work(job: Job):
            prog = Progress(
                phase=job.phase.emit, log=job.log.emit, files_total=job.files_total.emit,
                file_done=lambda name, ok, err: job.file_done.emit(name, ok, err or ""),
                should_stop=lambda: job.stop_requested,
            )
            return run(client, out, progress=prog, **opts)

        self.job = start_job(self, work, self._finished, self._failed)
        self.job.phase.connect(lambda m: (self.phase.setText(m), self.say(m)))
        self.job.log.connect(self.say)
        self.job.files_total.connect(self._on_files_total)
        self.job.file_done.connect(self._on_file_done)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop(self):
        if self.job:
            self.job.stop_requested = True
            self.stop_btn.setEnabled(False)
            self.phase.setText("Stopping after the current downloads…")

    def _on_files_total(self, n):
        self.files_n = n
        self.bar.setRange(0, max(n, 1))
        self.bar.setValue(0)
        self.bar.setFormat("%v / %m files")

    def _on_file_done(self, name, ok, err):
        if ok:
            self.files_ok += 1
        else:
            self.files_failed += 1
            self.say(f"✗ {name}: {err}")
        self.bar.setValue(self.files_ok + self.files_failed)
        self._tick()

    def _tick(self):
        elapsed = time.time() - self.started
        done = self.files_ok + self.files_failed
        eta = f"  ·  about {_fmt_secs(elapsed / done * (self.files_n - done))} left" if self.files_n and done and done < self.files_n else ""
        failed = f"  ·  {self.files_failed} failed" if self.files_failed else ""
        files = f"  ·  files {done}/{self.files_n}" if self.files_n else ""
        self.stats.setText(f"Elapsed {_fmt_secs(elapsed)}{files}{failed}{eta}")

    def _end(self):
        self.ticker.stop()
        self._tick()
        self.job = None
        self.start_btn.setEnabled(self.session is not None)
        self.stop_btn.setEnabled(False)

    def _finished(self, res):
        self._end()
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.bar.setFormat("Done")
        graded = sum(1 for t in res.tasks if any(g["display"] for g in t["grades"]))
        summary = (f"Done: {len(res.tasks)} tasks ({graded} with results), {sum(len(t['rubrics']) for t in res.tasks)} rubrics, "
                   f"{res.files_ok} new files" + (f", {res.files_skipped} already saved" if res.files_skipped else "")
                   + (f", {len(res.files_failed)} failed" if res.files_failed else ""))
        self.phase.setText(summary)
        self.say(summary)
        if res.changes:
            self.say(changes.describe(res.changes))
        if res.zip_path:
            self.say(f"ZIP: {res.zip_path}")
        self.synced.emit(res)

    def _failed(self, kind, msg):
        self._end()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setFormat("")
        self.phase.setText("Stopped." if kind == "cancelled" else "Sync failed.")
        self.say(msg)
        if kind == "session":
            self.session_expired.emit()
        elif kind == "error":
            QMessageBox.critical(self, "Something went wrong", msg)


# ── main window ──────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None):
        super().__init__()
        self.settings = settings or QSettings("CompassScraper", "CompassScraper")
        self.colors = theme.apply(QApplication.instance(), self.settings.value("theme", "System"))
        self.session: Session | None = None
        self.setWindowTitle("Compass Scraper")
        self.resize(1180, 780)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())
        self.pages = QStackedWidget()
        self.overview = Overview()
        self.timeline = TimelinePage()
        self.performance = PerformancePage()
        self.browse = BrowsePage(self.colors)
        self.sync = SyncPage(self.settings)
        for page in (self.overview, self.timeline, self.performance, self.browse, self.sync):
            self.pages.addWidget(page)
        for page in (self.overview, self.timeline, self.performance):
            page.c = self.colors
        self.performance.set_colors(self.colors)
        h.addWidget(self.pages, 1)
        self.setCentralWidget(root)

        self.sync.synced.connect(self._after_sync)
        self.sync.session_expired.connect(self._session_expired)
        self.sync.years_loaded.connect(self._maybe_autosync)
        self.overview.open_task.connect(self._open_task)
        self.overview.sync_requested.connect(lambda: self.nav.setCurrentRow(self.SYNC))
        self.browse.seen_changed.connect(self._seen_changed)
        self.browse.planner_changed.connect(self._planner_changed)
        self.timeline.changed.connect(self._planner_changed)
        self.timeline.open_task.connect(self._open_task)
        self.performance.open_task.connect(self._open_task)
        self._autosync_pending = self.settings.value("autosync", False, type=bool)
        self._shortcuts()

        out = Path(self.settings.value("out", str(DEFAULT_OUT))).expanduser()
        self.nav.setCurrentRow(self.OVERVIEW if self._load(out) else self.SYNC)
        self._set_session(None)
        QTimer.singleShot(100, self._try_saved_session)

    OVERVIEW, TIMELINE, PERFORMANCE, BROWSE, SYNC = range(5)
    PAGE_NAMES = ("Overview", "Timeline", "Performance", "Browse", "Sync")

    def _shortcuts(self):
        keys = {f"Ctrl+{i + 1}": (lambda i=i: self.nav.setCurrentRow(i)) for i in range(len(self.PAGE_NAMES))}
        keys.update({"Ctrl+R": self._sync_now, "F5": self._sync_now, "Ctrl+F": self._focus_search, "Ctrl+K": self.quick_find,
                     "Ctrl+N": self._new_item})
        for key, fn in keys.items():
            QShortcut(QKeySequence(key), self, activated=fn)

    def _focus_search(self):
        self.nav.setCurrentRow(self.BROWSE)
        self.browse.search.setFocus()
        self.browse.search.selectAll()

    def quick_find(self):
        if not self.browse.tasks:
            return None
        dlg = QuickFind(self.browse, self)
        dlg.chosen.connect(self._open_task)
        dlg.open()
        return dlg

    def _new_item(self):
        if self.browse.root:
            self.nav.setCurrentRow(self.TIMELINE)
            self.timeline.add_item()

    def _planner_changed(self):
        self.browse.refresh()
        self.overview.refresh()
        self.timeline.refresh()
        self.performance.refresh()

    def _sync_now(self):
        if self.session and not self.sync.job:
            self.nav.setCurrentRow(self.SYNC)
            self.sync.start()

    def _maybe_autosync(self):
        if self._autosync_pending and self.session:
            self._autosync_pending = False
            self.sync.say("Syncing automatically (turn this off on the Sync page).")
            self._sync_now()

    def _load(self, out: Path) -> bool:
        ok = self.browse.load(out)
        self.overview.set_source(self.browse)
        if ok:
            self.timeline.set_source(self.browse)
            self.performance.set_source(self.browse)
        self._update_badges()
        return ok

    def _update_badges(self):
        n = self.browse.unseen_count() if self.browse.tasks else 0
        self.nav.item(self.BROWSE).setText(f"Browse   ({n} new)" if n else "Browse")

    def _seen_changed(self):
        self.overview.refresh()
        self._update_badges()

    def _open_task(self, task_id):
        if isinstance(task_id, str) and task_id.startswith("my-"):
            self.nav.setCurrentRow(self.TIMELINE)
            return
        self.nav.setCurrentRow(self.BROWSE)
        self.browse.select_task(task_id)

    def _sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(240)
        v = QVBoxLayout(side)
        v.setContentsMargins(16, 18, 16, 14)
        v.setSpacing(10)
        v.addWidget(_label("Compass Scraper", "appTitle"))

        card, c = _card()
        self.who = _label("Not signed in")
        f = self.who.font()
        f.setBold(True)
        self.who.setFont(f)
        self.who.setWordWrap(True)
        self.where = _label("", "muted")
        c.addWidget(self.who)
        c.addWidget(self.where)
        row = QHBoxLayout()
        self.signin_btn = QPushButton("Sign in…")
        self.signin_btn.clicked.connect(self._sign_in)
        self.signout_btn = QPushButton("Sign out")
        self.signout_btn.setObjectName("link")
        self.signout_btn.clicked.connect(self._sign_out)
        row.addWidget(self.signin_btn)
        row.addWidget(self.signout_btn)
        row.addStretch(1)
        c.addLayout(row)
        v.addWidget(card)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.find_btn = QPushButton("Search everything…   Ctrl+K")
        self.find_btn.clicked.connect(self.quick_find)
        v.addWidget(self.find_btn)
        for i, name in enumerate(self.PAGE_NAMES):
            it = QListWidgetItem(name)
            it.setToolTip(f"Ctrl+{i + 1}")
            self.nav.addItem(it)
        self.nav.setFixedHeight(42 * len(self.PAGE_NAMES))
        self.nav.currentRowChanged.connect(lambda i: self.pages.setCurrentIndex(i))
        v.addWidget(self.nav)
        v.addStretch(1)

        th = QHBoxLayout()
        th.addWidget(_label("Theme", "muted"))
        self.theme = QComboBox()
        self.theme.addItems(["System", "Light", "Dark"])
        self.theme.setCurrentText(self.settings.value("theme", "System"))
        self.theme.currentTextChanged.connect(self._set_theme)
        th.addWidget(self.theme, 1)
        v.addLayout(th)
        if desktop.supported():
            self.menu_btn = QPushButton("Add to app menu")
            self.menu_btn.setObjectName("link")
            self.menu_btn.setToolTip("Adds Compass Scraper to your desktop's application launcher.")
            self.menu_btn.clicked.connect(self._install_desktop)
            v.addWidget(self.menu_btn, 0, Qt.AlignLeft)
        v.addWidget(_label(f"v{__version__}", "muted"))
        return side

    def _set_theme(self, mode: str):
        self.settings.setValue("theme", mode)
        self.colors = theme.apply(QApplication.instance(), mode)
        self.browse.set_colors(self.colors)
        self.overview.c = self.colors
        self.overview.refresh()
        self.timeline.set_colors(self.colors)
        self.performance.set_colors(self.colors)

    def _install_desktop(self):
        try:
            path = desktop.install()
        except OSError as e:
            QMessageBox.warning(self, "Couldn't add launcher", str(e))
            return
        QMessageBox.information(self, "Added to app menu", f"Compass Scraper is now in your application menu.\n\n{path}")

    def _set_session(self, s: Session | None, source: str = ""):
        self.session = s
        if s:
            self.who.setText(s.user_name or f"User {s.user_id}")
            host = self.where.fontMetrics().elidedText(s.host, Qt.ElideMiddle, 168)
            self.where.setText(f"{host}\nSigned in{' via ' + source if source else ''}")
            self.where.setToolTip(s.host)
            self.signin_btn.setText("Switch…")
        else:
            self.who.setText("Not signed in")
            self.where.setText("Use the browser you sign\nin to Compass with.")
            self.signin_btn.setText("Sign in…")
        self.signout_btn.setVisible(s is not None)
        self.sync.set_session(s)

    def _try_saved_session(self):
        saved = load_session(self.settings.value("host", DEFAULT_HOST))
        if not saved:
            return
        self.where.setText("Checking saved session…")

        def check(_):
            CompassClient(saved).check()
            return saved
        start_job(self, check, lambda s: self._set_session(s, "saved session"),
                  lambda kind, msg: self._set_session(None))

    def _sign_in(self):
        dlg = SignInDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted and dlg.session:
            self._set_session(dlg.session, dlg.browser.currentText() if dlg.browser.currentText() != "Auto" else "")
            self.nav.setCurrentRow(self.SYNC)

    def _sign_out(self):
        if self.session:
            forget_session(self.session.host)
        self._set_session(None)

    def _session_expired(self):
        self._sign_out()
        QMessageBox.warning(self, "Signed out", "Your Compass session expired. Sign in again; files already downloaded are kept.")
        self._sign_in()

    def _after_sync(self, res):
        if self._load(res.out_dir):
            self.nav.setCurrentRow(self.OVERVIEW)

    def closeEvent(self, e):
        job = self.sync.job
        if job:
            job.stop_requested = True
            job.wait(5000)
        super().closeEvent(e)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Compass Scraper")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("compass-scraper")
    app.setWindowIcon(QIcon(str(desktop.icon_path())))
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
