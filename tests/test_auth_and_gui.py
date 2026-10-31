"""Sign-in helpers and a headless run of the GUI against the fake Compass server."""
import os
import time

import pytest

from compass_scraper import auth, insights
from compass_scraper.client import CompassClient, SessionExpired

from test_end_to_end import USER, FakeCompass, server  # noqa: F401  (fixture)

COOKIE = [{"name": "ASP.NET_SessionId", "value": "abc", "domain": "127.0.0.1", "path": "/"}]


def test_parse_cookie_header():
    cookies = auth.parse_cookie_header("x.compass.education", "Cookie: ASP.NET_SessionId=abc; cpssid_x=1=2; username=max")
    assert [(c["name"], c["value"]) for c in cookies] == [("ASP.NET_SessionId", "abc"), ("cpssid_x", "1=2"), ("username", "max")]


def test_identify_reads_user_id_from_page(server):
    user_id, name = auth.identify("127.0.0.1", COOKIE, base_url=server)
    assert (user_id, name) == (USER, "Test Student")


def test_identify_detects_login_page(server):
    FakeCompass.logged_in = False
    with pytest.raises(SessionExpired):
        auth.identify("127.0.0.1", COOKIE, base_url=server)


def test_session_from_browser_tries_each(monkeypatch, server, tmp_path):
    monkeypatch.setenv("COMPASS_SCRAPER_HOME", str(tmp_path))
    calls = []

    def fake_cookies(host, browser):
        calls.append(browser)
        if browser == "Firefox":
            raise RuntimeError("profile not found")
        return [("Chromium (Default)", COOKIE)] if browser == "Chromium" else []

    monkeypatch.setattr(auth, "cookies_from_browser", fake_cookies)
    real_make = auth.make_session
    monkeypatch.setattr(auth, "make_session", lambda h, c, user_id=None: real_make(h, c, user_id, base_url=server))
    s = auth.session_from_browser("127.0.0.1", "Auto", log=lambda m: None)
    assert s.user_id == USER and calls[:5] == ["Firefox", "Zen", "Chrome", "Arc", "Chromium"]


@pytest.mark.skipif(not os.environ.get("QT_QPA_PLATFORM"), reason="set QT_QPA_PLATFORM=offscreen to run the GUI test")
def test_gui_full_run(monkeypatch, server, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from compass_scraper import gui

    monkeypatch.setenv("COMPASS_SCRAPER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(gui, "CompassClient", lambda s: CompassClient(s, base_url=server))
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setValue("out", str(tmp_path / "portfolio"))
    w = gui.MainWindow(settings)
    assert w.nav.currentRow() == w.SYNC  # nothing synced yet
    assert w.nav.count() == 5
    sess = auth.Session(host="127.0.0.1", user_id=USER, user_name="Test Student", cookies=COOKIE)

    def pump(until, timeout=20):
        end = time.time() + timeout
        while not until() and time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        assert until()

    w._set_session(sess, "test")
    assert w.who.text() == "Test Student"
    pump(lambda: w.sync.years.count() == 2)
    w.sync.start()
    pump(lambda: w.browse.tasks)
    assert w.sync.phase.text().startswith("Done: 3 tasks (1 with results), 1 rubrics, 4 new files")
    assert w.nav.currentRow() == w.OVERVIEW  # jumps to the Overview after a sync
    assert w.overview.stats["Tasks"].text() == "3" and w.overview.stats["With results"].text() == "1"
    assert w.overview.stats["Completed"].text() == "1"   # Task 1 is graded; the others are past due
    assert "First sync" in w.overview.info.text()
    w.overview.open_task.emit(29701)
    assert w.nav.currentRow() == w.BROWSE and w.browse.current_task()["id"] == 29701
    html = w.browse.detail.toHtml()
    assert "Task 1" in html and "Great work on the infographic CAT!" in html and "Above the expected level" in html

    w.browse.search.setText("running man")
    assert w.browse.tree.topLevelItemCount() == 1
    w.browse.search.setText("status:graded")
    assert w.browse.tree.topLevelItemCount() == 1 and w.browse.tree.topLevelItem(0).child(0).text(1) == "Graded"
    w.browse.search.setText("")
    w.browse.state.setCurrentIndex(w.browse.state.findData("Overdue"))
    assert sum(w.browse.tree.topLevelItem(i).childCount() for i in range(w.browse.tree.topLevelItemCount())) == 2
    w.browse.state.setCurrentIndex(0)

    # mark done, then it leaves the overdue list
    w.browse.select_task(29702)
    w.browse._toggle_done()
    assert w.browse.status_of(w.browse.current_task()) == "done"
    assert w.overview.stats["Completed"].text() == "2"

    # performance graphs
    w.nav.setCurrentRow(w.PERFORMANCE)
    assert w.performance.kind.currentText() == "VCE Number Scores"
    assert w.performance.stats["Graded"][0].text() == "1" and w.performance.trend.series[0]["name"] == "9DIG Digital Technologies"
    assert w.performance.stats["Average"][0].text() == "9.0"
    assert w.performance.table.item(0, 1).text() == "9.0" and w.performance.table.item(0, 1).toolTip().endswith("Above level")
    assert w.performance.dist.rows[0][0] == "Above the expected level"
    w.grab()

    # timeline: add, mark done, remove, export
    w.nav.setCurrentRow(w.TIMELINE)
    w.timeline.planner.add("Study for test", "2099-01-05T09:00:00+00:00", "9EN English")
    w.timeline._changed()
    titles = [w.timeline.tree.topLevelItem(i).text(0).strip() for i in range(w.timeline.tree.topLevelItemCount())]
    assert "★ Study for test" in titles
    item_id = w.timeline.planner.items[0]["id"]
    w.timeline.planner.toggle_done(item_id)
    assert insights.Planner.load(tmp_path / "portfolio").items[0]["done"]
    w.timeline.show_past.setChecked(True)
    w.timeline._remove(next(e for e in w.timeline.entries() if e.id == 29703))
    assert 29703 in insights.Planner.load(tmp_path / "portfolio").hidden
    assert w.timeline.export_ics(str(tmp_path / "due.ics")) >= 1
    assert "BEGIN:VEVENT" in (tmp_path / "due.ics").read_text()

    # universal search
    dlg = w.quick_find()
    dlg.box.setText("has:rubric")
    assert dlg.list.count() == 1
    dlg.box.setText("status:todo")
    assert dlg.list.count() == 1   # Task 3: Task 1 is graded and Task 2 is marked done
    dlg.close()
    w._set_theme("Dark")
    w.close()

    # a new window opens straight on the Overview with the last sync
    w2 = gui.MainWindow(settings)
    assert w2.nav.currentRow() == w2.OVERVIEW and len(w2.browse.tasks) == 3
    w2.close()


def test_desktop_install(monkeypatch, tmp_path):
    from compass_scraper import desktop
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    entry = desktop.install()
    text = entry.read_text()
    assert "Exec=" in text and "compass_scraper.gui" in text and "Icon=compass-scraper" in text
    assert (tmp_path / "icons/hicolor/scalable/apps/compass-scraper.svg").exists()
    desktop.uninstall()
    assert not entry.exists()


def test_macos_profiles_and_safari(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(auth, "MAC", True)
    sup = tmp_path / "Library" / "Application Support"
    for rel in ("Firefox/Profiles/abc.default-release", "zen/Profiles/xyz.Default (release)"):
        (sup / rel).mkdir(parents=True)
        (sup / rel / "cookies.sqlite").write_bytes(b"")
    (sup / "Google/Chrome/Profile 1").mkdir(parents=True)
    (sup / "Google/Chrome/Profile 1/Cookies").write_bytes(b"")
    safari = tmp_path / "Library/Containers/com.apple.Safari/Data/Library/Cookies"
    safari.mkdir(parents=True)
    (safari / "Cookies.binarycookies").write_bytes(b"")
    assert [p.parent.name for p in auth._profile_cookie_files("Zen")] == ["xyz.Default (release)"]
    assert len(auth._profile_cookie_files("Firefox")) == 1 and len(auth._profile_cookie_files("Chrome")) == 1
    assert auth._profile_cookie_files("Safari")[0].name == "Cookies.binarycookies"
    assert "Safari" in auth.supported_browsers()

    import browser_cookie3

    def blocked(**kw):
        raise PermissionError("Operation not permitted")
    monkeypatch.setattr(browser_cookie3, "safari", blocked)
    with pytest.raises(Exception, match="Full Disk Access"):
        auth.cookies_from_browser("example.compass.education", "Safari")
