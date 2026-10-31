"""Runs the whole scrape against a local fake Compass server.

The fake responses copy the field names and shapes recorded by the site mapper,
with made-up values.
"""
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from compass_scraper import scrape
from compass_scraper.client import CompassClient, Session, SessionExpired

USER = 6603
OPT_ABOVE = "5c8ae3163871c2a060ab8404"
COMMENT = "Max,\nGreat work on the infographic CAT!\nYou have clearly put a lot of effort into this."


def make_task(i, subject, **kw):
    t = {
        "__type": "LearningTaskDto:#Compass.Model",
        "id": 29700 + i, "taskId": 29700 + i, "name": f"Task {i}", "subjectId": 2300 + len(subject), "subjectName": subject,
        "activityName": subject[:4] + "A", "categoryId": 1, "dueDateTimestamp": f"2025-02-{10 + i:02d}T05:00:00Z",
        "createdTimestamp": "2025-01-30T00:00:00Z", "description": "<p>Research an issue.</p><p>Make an infographic.</p>",
        "attachments": None, "gradingItems": [], "rubricWikiNodeIds": [], "wikiNodeId": 220000 + i,
        "students": [{"userId": USER, "taskId": 29700 + i, "results": [], "rubricResults": [], "submissions": None,
                      "teacherResponses": None, "comments": None, "submissionStatus": 1, "submittedTimestamp": ""}],
    }
    t.update(kw)
    return t


TASKS = [
    make_task(1, "9DIG Digital Technologies",
              attachments=[{"id": "1b2c3d4e-0000-1111-2222-333344445555", "fileName": "Brief.docx", "name": "Brief", "contentUrl": None, "wikiNodeId": 1, "wikiNodeType": 1}],
              gradingItems=[
                  {"id": 151114, "name": "VCDT: Technologies - Digital Technologies", "shortName": "VCDT", "isPrimaryGrade": True, "ordinal": 0, "commentType": None},
                  {"id": 151115, "name": "Performance", "shortName": "Perf", "isPrimaryGrade": False, "ordinal": 1, "commentType": None},
                  {"id": 151117, "name": "Comment (Open)", "shortName": "Comment", "isPrimaryGrade": False, "ordinal": 3, "commentType": 1},
                  {"id": 151116, "name": "Effort", "shortName": "Eff", "isPrimaryGrade": False, "ordinal": 2, "commentType": None},
              ],
              rubricWikiNodeIds=[221335],
              students=[{"userId": USER, "taskId": 29701, "submissionStatus": 3, "submittedTimestamp": "2025-02-17T03:52:12Z",
                         "results": [
                             {"taskGradingItemId": 151114, "result": "9.0", "reportGradingSchemeOptionId": None},
                             {"taskGradingItemId": 151115, "result": "4", "reportGradingSchemeOptionId": OPT_ABOVE},
                             {"taskGradingItemId": 151116, "result": "Excellent", "reportGradingSchemeOptionId": None},
                             {"taskGradingItemId": 151117, "result": COMMENT, "reportGradingSchemeOptionId": None},
                         ],
                         "rubricResults": [{"rubricId": 1376, "rubricCriterionId": 7124, "rubricGradingScaleId": 40346}],
                         "submissions": [
                             {"id": 183771, "fileId": "aaaa", "fileName": "Environmental education.pdf", "timestamp": "2025-02-13T05:37:34Z", "contentUrl": None},
                             {"id": 184041, "fileId": "bbbb", "fileName": "Environmental education.pdf", "timestamp": "2025-02-17T03:52:12Z", "contentUrl": None},
                         ],
                         "teacherResponses": [{"id": 77910, "fileId": "cccc", "fileName": "Marked.docx", "timestamp": "2025-03-23T02:36:22Z", "contentUri": None}],
                         "comments": [{"comment": "ignored conversation"}]}]),
    make_task(2, "9EN English"),
    make_task(3, "9EN English", name="Essay: \"Running Man\" / analysis?"),
]
RUBRIC = {"id": 1376, "wikiNodeId": 221335, "name": "9DIG CAT 1 Infographics", "criteria": [
    {"id": 7124, "name": "Quality of data", "ordinal": 0, "description": None, "gradingScales": [
        {"id": 40345, "name": "8.5", "ordinal": 0, "contentDescriptors": [{"description": "Meaningful info", "ordinal": 0}]},
        {"id": 40346, "name": "9.0", "ordinal": 1, "contentDescriptors": [{"description": "Deep insight", "ordinal": 0}, {"description": "Validated", "ordinal": 1}]},
    ]},
]}


class FakeCompass(BaseHTTPRequestHandler):
    logged_in = True
    calls: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        if not FakeCompass.logged_in or "ASP.NET_SessionId=abc" not in (self.headers.get("Cookie") or ""):
            self.send_response(302)  # like Compass: bounce to the login page
            self.send_header("Location", "/login?handler=Login")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        return True

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/login":
            return self._send(200, b"<html>login page</html>", "text/html")
        if not self._auth():
            return
        if u.path == "/":
            page = ("<html><script>Compass.organisationUserId = %d; "
                    "Compass.organisationUserFirstAndLastname = 'Test Student';</script></html>" % USER)
            return self._send(200, page.encode(), "text/html")
        q = parse_qs(u.query)
        FakeCompass.calls.append(("GET", u.path, q))
        if u.path.endswith("GetAllAcademicGroups"):
            return self._send(200, {"d": [{"id": 13, "importIdentifier": "2024", "name": "2024 Academic", "isRelevant": False},
                                          {"id": 14, "importIdentifier": "2025", "name": "2025 Academic", "isRelevant": True}]})
        if u.path.endswith("GetGradingSchemesForLearningTasks"):
            return self._send(200, {"d": [{"name": "Performance", "options": [{"id": OPT_ABOVE, "displayValue": "Above the expected level", "colour": "#0a0"}]}]})
        if u.path.endswith("FileAssets.svc/DownloadFile"):
            return self._send(200, b"DOCX-BYTES", "application/octet-stream", {"Content-Disposition": "attachment; filename=Brief.docx"})
        if u.path.endswith("FileRequestHandler"):
            kind = q["FileDownloadType"][0]
            return self._send(200, f"FILE-{kind}-{q.get('submissionId', q.get('responseId'))[0]}".encode(), "application/pdf")
        self._send(404, b"", "text/plain")

    def do_POST(self):
        if not self._auth():
            return
        u = urlparse(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        FakeCompass.calls.append(("POST", u.path, body))
        assert parse_qs(u.query).get("sessionstate") == ["readonly"]
        if u.path.endswith("GetAllTaskCategories"):
            return self._send(200, {"d": [{"categoryId": 1, "categoryName": "Assessment", "categoryColour": "#E06055"}]})
        if u.path.endswith("GetAllLearningTasksByUserId"):
            assert body["userId"] == USER
            tasks = TASKS if body["academicGroupId"] == 14 else []
            page = tasks[body["start"]:body["start"] + body["limit"]]
            return self._send(200, {"d": {"data": page, "total": len(tasks)}})
        if u.path.endswith("GetRubricsByWikiNodeIds"):
            return self._send(200, {"d": [RUBRIC] if 221335 in body["wikiNodeIds"] else []})
        self._send(404, b"", "text/plain")


@pytest.fixture()
def server():
    FakeCompass.logged_in = True
    FakeCompass.calls = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeCompass)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def client_for(base):
    sess = Session(host="127.0.0.1", user_id=USER, user_name="Test Student",
                   cookies=[{"name": "ASP.NET_SessionId", "value": "abc", "domain": "127.0.0.1", "path": "/"}])
    return CompassClient(sess, base_url=base)


def test_full_run(server, tmp_path, monkeypatch):
    monkeypatch.setattr(CompassClient, "PAGE_SIZE", 2)  # force paging: 3 tasks over 2 pages
    out = tmp_path / "portfolio"
    res = scrape.run(client_for(server), out)

    assert [t["id"] for t in res.tasks] == [29701, 29702, 29703]
    pages = [c for c in FakeCompass.calls if c[1].endswith("GetAllLearningTasksByUserId")]
    assert len(pages) == 3  # 2024 (empty) + two pages of 2025

    t = res.tasks[0]
    assert t["category"] == "Assessment" and t["year"] == "2025 Academic"
    rows = {g["item"]: g for g in t["grades"]}
    assert [g["item"] for g in t["grades"]] == ["VCDT: Technologies - Digital Technologies", "Performance", "Effort", "Comment (Open)"]
    assert rows["Performance"]["display"] == "Above the expected level"
    assert rows["Comment (Open)"]["display"] == COMMENT and rows["Comment (Open)"]["isComment"]
    assert t["primaryGrade"] == "9.0"
    assert t["descriptionText"] == "Research an issue.\nMake an infographic."

    rub = t["rubrics"][0]
    assert rub["columns"] == ["8.5", "9.0"]
    assert rub["criteria"][0]["awarded"] == "9.0"
    assert [c["awarded"] for c in rub["criteria"][0]["cells"]] == [False, True]

    # files: right URLs, right folders, duplicate names kept apart
    assert res.files_ok == 4 and not res.files_failed
    folder = out / t["folder"]
    assert (folder / "Attachments" / "Brief.docx").read_bytes() == b"DOCX-BYTES"
    assert (folder / "Submissions" / "Environmental education.pdf").read_bytes() == b"FILE-2-183771"
    assert (folder / "Submissions" / "Environmental education (2).pdf").read_bytes() == b"FILE-2-184041"
    assert (folder / "Teacher responses" / "Marked.docx").read_bytes() == b"FILE-4-77910"
    assert (folder / "Rubric - 9DIG CAT 1 Infographics.html").exists()
    assert json.loads((folder / "task.json").read_text())["grades"][3]["display"] == COMMENT

    # odd characters in task names make safe folder names
    assert "Essay_ _Running Man_ _ analysis_ [29703]" in res.tasks[2]["folder"]

    html = (out / "index.html").read_text()
    assert "Great work on the infographic CAT!" in html and "<\\/" not in json.dumps(COMMENT)
    data = json.loads((out / "data.json").read_text())
    assert data["student"]["name"] == "Test Student" and len(data["tasks"]) == 3

    with zipfile.ZipFile(res.zip_path) as z:
        names = z.namelist()
    assert "portfolio/index.html" in names and any(n.endswith("Marked.docx") for n in names)

    # second run resumes: nothing downloaded again
    res2 = scrape.run(client_for(server), out, zip_output=False)
    assert res2.files_ok == 0 and res2.files_skipped == 4


def test_year_filter(server, tmp_path):
    res = scrape.run(client_for(server), tmp_path / "o", years=["2024"], download=False, zip_output=False)
    assert res.tasks == []
    with pytest.raises(Exception, match="Available: 2024, 2025"):
        scrape.run(client_for(server), tmp_path / "o", years=["1999"])


def test_expired_session(server):
    FakeCompass.logged_in = False
    with pytest.raises(SessionExpired):
        client_for(server).check()


def test_changes_between_syncs(server, tmp_path, monkeypatch):
    from compass_scraper import changes

    out = tmp_path / "p"
    first = scrape.run(client_for(server), out, download=False, zip_output=False)
    assert first.changes["firstSync"] and all(t["changes"] == [] for t in first.tasks)

    # teacher marks Task 2, adds feedback, and a new task appears
    t2 = make_task(2, "9EN English", gradingItems=[
        {"id": 9001, "name": "Grade", "shortName": "G", "isPrimaryGrade": True, "ordinal": 0, "commentType": None},
        {"id": 9002, "name": "Comment (Open)", "shortName": "C", "isPrimaryGrade": False, "ordinal": 1, "commentType": 1}])
    t2["students"][0]["results"] = [{"taskGradingItemId": 9001, "result": "B+", "reportGradingSchemeOptionId": None},
                                    {"taskGradingItemId": 9002, "result": "Nice essay.", "reportGradingSchemeOptionId": None}]
    monkeypatch.setattr(__import__(__name__), "TASKS", [TASKS[0], t2, TASKS[2], make_task(4, "9MA Maths")])
    second = scrape.run(client_for(server), out, download=False, zip_output=False)
    s = second.changes
    assert (s["newTasks"], s["newResults"], s["newFeedback"]) == (1, 1, 1)
    assert changes.describe(s) == "1 new task, 1 new result, 1 new piece of feedback"
    by_id = {t["id"]: t for t in second.tasks}
    assert [c["text"] for c in by_id[29702]["changes"]] == ["New result: Grade", "New feedback"]
    assert by_id[29701]["changes"] == []

    # marking as seen, and changes carry over to the next sync until then
    seen = {changes.seen_key(by_id[29702], c) for c in by_id[29702]["changes"]}
    changes.save_seen(out, seen)
    assert not changes.unseen(by_id[29702], changes.load_seen(out))
    third = scrape.run(client_for(server), out, download=False, zip_output=False)
    assert changes.describe(third.changes) == "Nothing new since the last sync."
    assert len({t["id"]: t for t in third.tasks}[29704]["changes"]) == 1


def test_insights():
    from datetime import datetime, timezone
    from compass_scraper import insights as I

    at = datetime(2025, 3, 1, tzinfo=timezone.utc)
    t = {"id": 1, "grades": [], "rubrics": [], "dueDate": "2025-03-04T00:00:00Z"}
    assert I.status(t, at=at) == "due_soon"
    assert I.status({**t, "dueDate": "2025-04-30T00:00:00Z"}, at=at) == "pending"
    assert I.status({**t, "dueDate": "2025-02-01T00:00:00Z"}, at=at) == "overdue"
    assert I.status({**t, "dueDate": "2025-02-01T00:00:00Z"}, {1}, at=at) == "done"
    assert I.status({**t, "submissions": [{"id": 5}]}, at=at) == "submitted"
    assert I.status({**t, "grades": [{"display": "B", "isComment": False}]}, at=at) == "graded"
    assert I.status({**t, "dueDate": None}, at=at) == "no_date"

    assert I.score({"display": "17/20"}).value == 85
    assert I.score({"display": "Above the expected level"}).value == 75
    assert I.score({"display": "Well above the expected level"}).value == 100
    assert I.score({"display": "Nice work", "isComment": True}) is None
    assert I.score({"display": "82", "item": "Exam %"}).kind == "percent" and I.score({"display": "9.5", "item": "VCS: Science"}).kind == "number"
    t2 = {"grades": [{"item": "Performance", "display": "Towards the expected level"}, {"item": "Exam %", "display": "62"},
                     {"item": "VCE", "display": "8.5", "isPrimary": True}]}
    # a percentage makes it a SAC (or an Exam by name), never also a VCE number score
    assert I.mark_category(t2) == I.SAC and I.task_score(t2, I.SAC).value == 62 and I.task_score(t2, I.VC) is None
    assert I.mark_category({**t2, "name": "Semester 1 Exam"}) == I.EXAM and I.task_score({**t2, "name": "Exam 2"}, I.SAC) is None
    t3 = {"name": "CAT 2", "grades": [{"item": "VCE", "display": "8.5", "isPrimary": True}, {"item": "Effort", "display": "Good"}]}
    assert I.mark_category(t3) == I.VC and I.task_score(t3, I.VC).value == 8.5 and I.task_level(t2) == "Towards"
    # a bare number too big to be a level score is a percentage (e.g. Applied Computing: 100)
    ac = {"name": "Unit 1 Outcome 2", "grades": [{"item": "VCE Applied Computing", "display": "100", "isPrimary": True}]}
    assert I.mark_category(ac) == I.SAC and I.task_score(ac, I.SAC).value == 100 and I.task_score(ac, I.VC) is None
    assert I.mark_category({"name": "x", "grades": [{"item": "Result", "display": "12.5"}]}) == I.VC
    assert I.counts_for_performance({"category": "Assessment"}) and I.counts_for_performance({"category": "Assignment"})
    assert not I.counts_for_performance({"category": "Homework"}) and not I.counts_for_performance({})

    q = I.parse_query('essay status:graded subject:"9EN English" has:rubric')
    assert q.words == ["essay"] and q.filters == {"status": ["graded"], "subject": ["9en english"], "type": ["rubric"]}
    task = {"name": "Essay", "subject": "9EN English", "grades": [{"display": "A"}], "rubrics": [{"x": 1}]}
    assert I.matches(task, q, "graded") and not I.matches(task, q, "overdue")
    assert I.matches(task, I.parse_query("status:todo"), "overdue") and I.matches(task, I.parse_query("status:completed"), "done")
    assert not I.matches(task, I.parse_query("has:submission"), "graded")


def test_planner_and_ics(tmp_path):
    from compass_scraper import insights as I

    p = I.Planner.load(tmp_path)
    item = p.add("Study", "2030-05-01T09:00:00+10:00", "Maths", "chapter 4")
    p.toggle_done(7)
    p.remove(8)
    again = I.Planner.load(tmp_path)
    assert again.items[0]["title"] == "Study" and again.done == {7} and again.hidden == {8}
    again.remove(item["id"])
    assert I.Planner.load(tmp_path).items == []

    entries = I.timeline([{"id": 7, "name": "Essay, part 1", "subject": "English", "dueDate": "2030-05-02T00:00:00Z", "grades": [], "rubrics": []}], p)
    ics = I.to_ics(entries)
    assert "SUMMARY:Due: Essay\\, part 1" in ics and "DTSTART:20300502T000000Z" in ics and ics.count("BEGIN:VEVENT") == 2
