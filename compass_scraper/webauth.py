"""“Sign in here”: a small browser window inside the app where you sign in to Compass yourself.

Works the same on Windows, macOS and Linux because the app keeps its own cookie
store, so nothing has to be read from another browser. The window keeps its own
profile in ~/.compass-scraper/web, so you usually stay signed in between runs.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .auth import make_session, save_session, session_path


def available() -> bool:
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
        return True
    except ImportError:
        return False


class WebSignIn(QDialog):
    signed_in = Signal(object)   # auth Session

    def __init__(self, host: str, start_job, parent=None, base_url: str | None = None):
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView

        super().__init__(parent)
        self.host = host
        self.base_url = base_url or f"https://{host}"
        self.start_job = start_job
        self.session = None
        self.cookies: dict[tuple[str, str, str], dict] = {}
        self.checking = False
        self.setWindowTitle("Sign in to Compass")
        self.resize(980, 760)

        store = Path(session_path(host)).parent / "web"
        self.profile = QWebEngineProfile("compass-scraper")  # deleted after the page, in done()
        self.profile.setPersistentStoragePath(str(store))
        self.profile.setCachePath(str(store / "cache"))
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.AllowPersistentCookies)
        cookie_store = self.profile.cookieStore()
        cookie_store.cookieAdded.connect(self._cookie_added)
        cookie_store.cookieRemoved.connect(self._cookie_removed)
        cookie_store.loadAllCookies()

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 8, 12, 8)
        self.status = QLabel("Sign in to Compass below. The window closes by itself once you're in.")
        self.status.setObjectName("muted")
        self.done_btn = QPushButton("I'm signed in")
        self.done_btn.setObjectName("primary")
        self.done_btn.clicked.connect(self.check_now)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        bar.addWidget(self.status, 1)
        bar.addWidget(cancel)
        bar.addWidget(self.done_btn)
        v.addLayout(bar)

        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(self.profile, self.view))
        self.view.urlChanged.connect(self._url_changed)
        self.view.loadFinished.connect(lambda ok: ok and self._maybe_check())
        v.addWidget(self.view, 1)
        self.view.load(QUrl(self.base_url + "/"))

    # cookies
    def _key(self, c):
        return bytes(c.name()).decode("utf-8", "replace"), c.domain(), c.path()

    def _cookie_added(self, c):
        name, domain, path = self._key(c)
        d = domain.lstrip(".")
        if self.host.endswith(d) or d.endswith("compass.education") or d == QUrl(self.base_url).host():
            self.cookies[(name, domain, path)] = {"name": name, "value": bytes(c.value()).decode("utf-8", "replace"),
                                                  "domain": domain, "path": path or "/"}

    def _cookie_removed(self, c):
        self.cookies.pop(self._key(c), None)

    # detection
    def _url_changed(self, url: QUrl):
        self._maybe_check()

    def _maybe_check(self):
        url = self.view.url()
        if url.host().lower() == QUrl(self.base_url).host().lower() and "login" not in url.toString().lower():
            QTimer.singleShot(400, self.check_now)

    def check_now(self):
        if self.checking or not self.cookies:
            return
        self.checking = True
        self.status.setText("Checking your Compass session…")
        cookies = list(self.cookies.values())
        host, base = self.host, (self.base_url if self.base_url != f"https://{self.host}" else None)

        def work(_):
            s = make_session(host, cookies, base_url=base)
            save_session(s)
            return s

        def ok(s):
            self.checking = False
            self.session = s
            self.signed_in.emit(s)
            self.accept()

        def fail(_kind, msg):
            self.checking = False
            self.status.setText("Not signed in yet. Finish signing in, then click “I'm signed in”.")
        self.start_job(self, work, ok, fail)

    def done(self, result):
        # The page must go before its profile, or Qt warns and may crash on exit.
        self.view.setParent(None)
        self.view.deleteLater()
        QTimer.singleShot(0, self.profile.deleteLater)
        super().done(result)
