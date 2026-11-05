"""School reports import: parsing helpers, the saved reports.json, and the Reports page (no real reports needed)."""
import json
import os
import zipfile

import pytest

from compass_scraper import reports
from compass_scraper.reports import Report, ReportError, ReportStore


def test_cycle_info_from_file_names():
    assert reports._cycle_info("2025 - 2025 Term 3 Learning Behaviour Reports (August) 2025.pdf") == (2025, "learning behaviour", "Term 3", 8)
    assert reports._cycle_info("2023 - Semester 2 Reports (December) 2023.pdf") == (2023, "semester", "Semester 2", 12)
    assert reports._cycle_info("2024 - Semester 1 Reports 2024.pdf")[3] == 6      # no month: from the period
    with pytest.raises(ReportError):
        reports._cycle_info("Timetable.pdf")


@pytest.mark.parametrize("raw, name", [
    ("Learning Habits Agency in learning", "Agency in learning"),
    ("Works productively in class", "Works productively"),
    ("Completes required work", "Completes required work"),
    ("Seeks assistance when necessary", "Seeks assistance when necessary"),
    ("Works in a team", "Works in a team"),
    ("Respects the rights of others to learn", "Respects the rights of others to learn"),
    ("Something new", "Something new"),
])
def test_behaviour_names_are_normalised(raw, name):
    assert reports.behaviour_name(raw) == name


def test_ratings():
    assert reports.rating_value("Needs Attention") == 1 and reports.rating_value("Excellent") == 5
    assert reports.rating_value("?") is None
    subject = {"behaviours": {"Agency in learning": {"1": "Good", "3": "Excellent", "2": "Very Good"}}}
    assert reports.latest_ratings(subject) == {"Agency in learning": "Excellent"}


def _report(cycle="2024 - Semester 1 Reports (June) 2024", year=2024, period="Semester 1", month=6, level=8.5):
    return Report(cycle, year, "semester", period, month, "Year 8",
                  [{"area": "English", "strand": "Writing", "level": level, "expected": [8.0, 8.5], "beyond": 11}],
                  [{"subject": "8 English", "teacher": "A TEACHER", "attendance": 95.0,
                    "behaviours": {"Agency in learning": {"1": "Good", "2": "Very Good"}}}])


def test_store_round_trip_and_order(tmp_path):
    store = ReportStore(tmp_path, [_report(), _report("2023 - Semester 2 Reports (December) 2023", 2023, "Semester 2", 12, 7.5)])
    store.save()
    data = json.loads((tmp_path / reports.REPORTS_FILE).read_text())
    assert set(data) == {"version", "imported", "reports"}
    # only the four kinds of data are kept for each subject
    assert set(data["reports"][0]["subjects"][0]) == {"subject", "teacher", "attendance", "behaviours"}
    loaded = ReportStore.load(tmp_path)
    assert [r.year for r in loaded.reports] == [2023, 2024]
    assert loaded.strands() == [("English", "Writing")]
    assert loaded.behaviour_names() == ["Agency in learning"]
    assert not list(tmp_path.glob(".reports-*"))      # no temp files left behind


def test_load_survives_missing_or_broken_file(tmp_path):
    assert ReportStore.load(tmp_path).reports == []
    (tmp_path / reports.REPORTS_FILE).write_text("{not json")
    assert ReportStore.load(tmp_path).reports == []
    assert ReportStore.load(None).reports == []


def test_import_rejects_files_that_arent_reports(tmp_path):
    store = ReportStore(tmp_path)
    bad = tmp_path / "notes.zip"
    bad.write_text("hello")
    with pytest.raises(ReportError):
        store.import_zip(bad)
    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("readme.txt", "no pdfs")
    with pytest.raises(ReportError):
        store.import_zip(empty)
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("2024 HeadStart Reports 2024.pdf", b"%PDF-1.4")
        z.writestr("2024 - Semester 1 Reports (June) 2024.pdf", b"not really a pdf")
    with pytest.raises(ReportError):
        store.import_zip(other)
    assert not (tmp_path / reports.REPORTS_FILE).exists()     # nothing saved when nothing could be read


def test_import_replaces_the_same_cycle(tmp_path, monkeypatch):
    store = ReportStore(tmp_path, [_report(level=7.0)])
    monkeypatch.setattr(reports, "read_pdf", lambda data, name, guide: _report(level=9.0))
    z = tmp_path / "r.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("2024 - Semester 1 Reports (June) 2024.pdf", b"%PDF")
        f.writestr("2024 HeadStart Reports (Nov) 2024.pdf", b"%PDF")
    assert store.import_zip(z) == (1, 1)
    loaded = ReportStore.load(tmp_path)
    assert len(loaded.reports) == 1 and loaded.reports[0].curriculum[0]["level"] == 9.0


def test_level_helpers():
    from compass_scraper.reports_page import level_text, level_vs_expected
    assert level_text(7.5) == "7.5" and level_text(None) == "–" and level_text(11.5, 11) == "Beyond 10"
    assert level_vs_expected(7.0, [7.0, 7.5]) == "At"
    assert level_vs_expected(6.5, [7.0, 7.5]) == "Towards"
    assert level_vs_expected(6.0, [7.0, 7.5]) == "Below"
    assert level_vs_expected(8.0, [7.0, 7.5]) == "Above"
    assert level_vs_expected(8.5, [7.0, 7.5]) == "Well above"
    assert level_vs_expected(8.5, None) is None


def test_reports_page_shows_saved_data(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from compass_scraper import theme
    from compass_scraper.reports_page import ReportsPage

    app = QApplication.instance() or QApplication([])
    page = ReportsPage()
    page.set_colors(theme.apply(app, "Light"))
    page.set_root(tmp_path)
    assert page.stack.currentIndex() == 0                 # empty state with instructions
    ReportStore(tmp_path, [_report()]).save()
    page.set_root(tmp_path)
    assert page.stack.currentIndex() == 1
    assert page.levels.item(0, 2).text() == "8.5"
    page.view._clicked(page.SUBJECTS)
    assert page.stack.currentIndex() == 2
    assert page.subjects.item(0, 1).text() == "A TEACHER"
    assert page.subjects.item(0, 2).text() == "95%"
    assert page.subjects.item(0, 3).text() == "Very Good"
