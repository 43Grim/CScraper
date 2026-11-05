"""Sign-in helpers and a headless run of the GUI against the fake Compass server."""
import os
import time

import pytest

from compass_scraper import auth, desktop, insights
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
    assert w.menu_btn.text() == f"Add to {desktop.place()}"
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
    assert w.performance.kind.currentText() == "CATs" and w.performance.view.current() == "number"
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


def test_desktop_install_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert desktop.supported() and desktop.place() == "app menu"
    entry = desktop.install()
    text = entry.read_text()
    assert "Exec=" in text and "compass_scraper.gui" in text and "Icon=compass-scraper" in text
    assert (tmp_path / "icons/hicolor/scalable/apps/compass-scraper.svg").read_bytes() == desktop.icon_path().read_bytes()
    # a packaged app starts itself, without Python's arguments
    monkeypatch.setattr(desktop.sys, "frozen", True, raising=False)
    text = desktop.install().read_text()
    assert f'Exec="{desktop.sys.executable}"\n' in text and "compass_scraper.gui" not in text and "Path=" not in text


def test_desktop_install_windows(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(desktop.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    monkeypatch.setattr(desktop.sys, "frozen", True, raising=False)
    assert desktop.supported() and desktop.place() == "Start menu"
    link = desktop.install()
    assert link == tmp_path / "Microsoft/Windows/Start Menu/Programs/Compass Scraper.lnk" and link.parent.is_dir()
    cmd, kw = calls[0]
    assert cmd[0] == "powershell" and "CreateShortcut" in cmd[-1] and str(tmp_path) not in cmd[-1]
    assert kw["env"]["CS_LINK"] == str(link) and kw["env"]["CS_TARGET"] == desktop.sys.executable and kw["env"]["CS_ARGS"] == ""

    def fail(cmd, **kw):
        raise desktop.subprocess.CalledProcessError(1, cmd, stderr="access denied")
    monkeypatch.setattr(desktop.subprocess, "run", fail)
    with pytest.raises(OSError, match="access denied"):
        desktop.install()


def test_desktop_install_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    assert desktop.supported() and desktop.place() == "Applications"
    real_access = desktop.os.access
    monkeypatch.setattr(desktop.os, "access", lambda p, m: False if str(p) == "/Applications" else real_access(p, m))

    # running from source: a small launcher
    app = desktop.install()
    assert app == tmp_path / "Applications/Compass Scraper.app"
    script = app / "Contents/MacOS/Compass Scraper"
    assert "compass_scraper.gui" in script.read_text() and desktop.os.access(script, desktop.os.X_OK)

    # a packaged app is copied there, replacing the old copy
    bundle = tmp_path / "Downloads/Compass Scraper.app"
    (bundle / "Contents/MacOS").mkdir(parents=True)
    (bundle / "Contents/MacOS/Compass Scraper").write_text("real app")
    monkeypatch.setattr(desktop.sys, "frozen", True, raising=False)
    monkeypatch.setattr(desktop.sys, "executable", str(bundle / "Contents/MacOS/Compass Scraper"))

    def ditto(cmd, **kw):
        assert cmd[0] == "ditto"
        desktop.shutil.copytree(cmd[1], cmd[2])
    monkeypatch.setattr(desktop.subprocess, "run", ditto)
    assert desktop.install() == app and script.read_text() == "real app"
    assert not (tmp_path / "Applications/.Compass Scraper.app.tmp").exists()

    # a failed copy leaves the existing app alone
    def fail(cmd, **kw):
        raise desktop.subprocess.CalledProcessError(1, cmd, stderr="disk full")
    monkeypatch.setattr(desktop.subprocess, "run", fail)
    with pytest.raises(OSError, match="disk full"):
        desktop.install()
    assert script.read_text() == "real app"

    # already in Applications: nothing to do
    monkeypatch.setattr(desktop.sys, "executable", str(script))
    assert desktop.install() == app


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


def _perf_page(qapp_tasks):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from compass_scraper import theme
    from compass_scraper.performance import PerformancePage
    app = QApplication.instance() or QApplication([])
    page = PerformancePage()
    page.set_colors(theme.apply(app, "Dark"))
    page.set_source(SimpleNamespace(tasks=qapp_tasks, seen=set(), planner=insights.Planner()))
    return page


def _toggle(page, label):
    from PySide6.QtWidgets import QPushButton
    next(b for b in page.view.findChildren(QPushButton) if b.text() == label).click()


def test_performance_toggles():
    from test_end_to_end import _maths_cat, _vce_sac
    dated = lambda t, i: {**t, "id": i, "year": "2026 Academic", "dueDate": f"2026-0{i}-10T00:00:00Z"}
    page = _perf_page([dated(_maths_cat(), 1), dated(_vce_sac("Medium - High", "70"), 2), dated(_vce_sac(), 3)])
    combo = page.kind
    assert [combo.itemText(i) for i in range(combo.count())] == ["CATs", "SACs"]

    # Year 10 CATs: number scores first, then percentages
    assert not page.view.isHidden() and page.view.current() == "number"
    assert page.stats["Average"][0].text() == "10.5" and page.table.item(0, 1).text() == "10.5"
    assert page.table.item(0, 1).toolTip().endswith("Above level")
    _toggle(page, "Percentages")
    assert page.stats["Average"][0].text() == "65%" and page.trend.ticks[-1][1] == "100%"

    # Year 11 SACs: percentage, then named performance bands instead of numbers
    combo.setCurrentIndex(1)
    assert page.view.current() == "percent" and page.stats["Average"][0].text() == "84%"
    _toggle(page, "Performance")
    assert [lbl for _, lbl in page.trend.ticks][-1] == "High - Excellent" and page.trend.series[0]["points"][-1][2] == "High - Excellent"
    assert page.table.item(0, 1).text() == "Medium - High" and page.table.item(0, 2).text() == "High - Excellent"
    assert page.key_labels["Well above"].text() == "Excellent"
    assert {r[0] for r in page.dist.rows} == {"Medium - High", "High - Excellent"}
    assert page.subjects.rows[0][2] in insights.PERFORMANCE_BANDS
    page.grab()

    # each category remembers its view
    combo.setCurrentIndex(0)
    assert page.view.current() == "percent" and page.key_labels["Well above"].text() == "Well above"
    combo.setCurrentIndex(1)
    assert page.view.current() == "performance"

    # a year with no marks shows plain labels, whatever was on screen before
    page.browse.tasks = [{"id": 9, "name": "Unmarked", "year": "2026 Academic", "subject": "9SCI", "category": "Assessment", "grades": []}]
    page.set_source(page.browse)
    assert page.kind.currentText() == "VCE Number Scores" and page.view.isHidden()
    assert {k: v[1].text() for k, v in page.stats.items() if k != "Completed"} == {k: k for k in ("Graded", "Average", "Strongest", "Trend")}
    assert page.trend.message == "No marks for this year yet."


def test_performance_toggle_hidden_for_other_categories():
    from test_end_to_end import _vce_sac
    exam = {**_vce_sac(), "id": 1, "year": "2026 Academic", "name": "Exam", "dueDate": "2026-06-10T00:00:00Z"}
    page = _perf_page([exam])
    assert page.kind.currentText() == "Exams" and page.view.isHidden() and page.stats["Average"][0].text() == "97%"
