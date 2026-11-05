"""Task status, score normalisation, the planner (your own timeline items) and search queries.

Pure Python with no Qt, so the CLI, the HTML report and the tests can all use it.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

DUE_SOON_DAYS = 7


_HEADSTART = re.compile(r"head\s*start", re.I)


def is_academic_year(name: str | None) -> bool:
    """False for HeadStart years, which the app leaves out entirely."""
    return not _HEADSTART.search(name or "")


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.astimezone()


def now() -> datetime:
    return datetime.now(timezone.utc)


# ── status ───────────────────────────────────────────────────────────
STATUSES = {
    # key: (label, complete?)
    "graded": ("Graded", True),
    "submitted": ("Submitted", True),
    "done": ("Done", True),
    "overdue": ("Overdue", False),
    "due_soon": ("Due soon", False),
    "pending": ("Pending", False),
    "no_date": ("No due date", False),
}
STATUS_FILTERS = {
    "To do": {"overdue", "due_soon", "pending", "no_date"},
    "Overdue": {"overdue"},
    "Due soon": {"due_soon"},
    "Pending": {"pending", "due_soon", "no_date"},
    "Completed": {"graded", "submitted", "done"},
    "Submitted": {"submitted"},
    "Graded": {"graded"},
    "Marked done": {"done"},
}


def has_grades(t: dict) -> bool:
    """Any row on the task's Grades table has a value (a comment alone counts)."""
    return any(g.get("display") for g in t.get("grades", []))


def has_results(t: dict) -> bool:
    return any(g.get("display") and not g.get("isComment") for g in t.get("grades", [])) or \
        any(c.get("awarded") for r in t.get("rubrics", []) for c in r.get("criteria", []))


def is_submitted(t: dict) -> bool:
    return bool(t.get("submissions") or t.get("submittedTimestamp"))


def status(t: dict, done_ids: set | None = None, at: datetime | None = None) -> str:
    """graded > submitted > done (marked by you) > overdue / due_soon / pending / no_date."""
    if has_results(t) or has_grades(t):  # a comment alone counts as marked
        return "graded"
    if is_submitted(t):
        return "submitted"
    if done_ids and (t.get("id") in done_ids or str(t.get("id")) in done_ids):
        return "done"
    due = parse_dt(t.get("dueDate"))
    if not due:
        return "no_date"
    at = at or now()
    if due < at:
        return "overdue"
    return "due_soon" if due - at <= timedelta(days=DUE_SOON_DAYS) else "pending"


def status_label(key: str) -> str:
    return STATUSES[key][0]


def is_complete(key: str) -> bool:
    return STATUSES[key][1]


# ── scores ───────────────────────────────────────────────────────────
# Scheme labels are mapped to 0–100 so different subjects can share an axis.
_WORDS = [
    (r"well above", 100), (r"well below", 0), (r"above", 75), (r"below|towards", 25), (r"\bat (the )?(expected|standard|level)|at standard|meets|expected", 50),
    (r"outstanding|exceptional|excellent", 100), (r"very good|very high", 80), (r"\bhigh\b", 75), (r"\bgood\b|consistent", 65),
    (r"satisfactory|sound|fair|medium|developing|competent", 45), (r"needs? (attention|improvement)|inconsistent|limited|\blow\b|basic", 20),
    (r"unsatisfactory|poor|not (yet )?(demonstrated|shown|submitted)|very low|\bns\b|\bn/?a\b", 0),
]
_LETTERS = {"A+": 100, "A": 93, "A-": 87, "B+": 80, "B": 73, "B-": 67, "C+": 60, "C": 53, "C-": 47,
            "D+": 40, "D": 33, "D-": 27, "E+": 20, "E": 15, "E-": 10, "UG": 0, "N": 0, "F": 0}
_NUM = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(%?)\s*$")
_FRAC = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:/|out of)\s*(\d+(?:\.\d+)?)\s*$", re.I)


VC_MAX = 13.0   # Victorian Curriculum / VCE level scores sit roughly between 0 and 12.5
_PCT_NAME = re.compile(r"%|percent|\bsac\b|\bexam|\bperformance\b", re.I)
_VC_ROW = re.compile(r"\bVC(?!E\b)[A-Z0-9]+\b")   # curriculum codes such as VCS, VCM2MA or VCERV, but not plain "VCE"


def _looks_like_percent(g: dict, v: float) -> bool:
    """A bare number is a percentage when the row says so, or when it's too big to be a level score (e.g. 100, 82)."""
    name = g.get("item") or ""
    if v <= VC_MAX and (g.get("scheme") == "Victorian Curriculum" or _VC_ROW.search(name)):
        return False   # the row's title says it's a curriculum number score
    if _PCT_NAME.search(name):
        return True
    return v > VC_MAX and v <= 100


@dataclass
class Score:
    value: float          # 0–100 for percent/scheme/letter, raw for "number"
    kind: str             # "percent", "scheme", "letter" or "number"
    label: str


def score(g: dict) -> Score | None:
    """Turns one grade row into a number, or None for comments and unreadable values."""
    if g.get("isComment"):
        return None
    text = str(g.get("display") or "").strip()
    if not text:
        return None
    m = _NUM.match(text)
    if m:
        v = float(m.group(1))
        pct = bool(m.group(2)) or _looks_like_percent(g, v)
        return Score(v, "percent" if pct else "number", text)
    m = _FRAC.match(text)
    if m and float(m.group(2)):
        return Score(round(100 * float(m.group(1)) / float(m.group(2)), 1), "percent", text)
    if text.upper() in _LETTERS:
        return Score(_LETTERS[text.upper()], "letter", text)
    low = text.lower()
    for pattern, v in _WORDS:
        if re.search(pattern, low):
            return Score(v, "scheme", text)
    return None


VC = "VCE Number Scores"
CAT = "CATs"
SAC = "SACs"
EXAM = "Exams"
# Each category's marks, the default first.
SCORE_KINDS = {VC: ("number",), CAT: ("number", "percent"), SAC: ("percent", "performance"), EXAM: ("percent",)}
SCORE_VIEWS = {CAT: (("number", "VCE Number Scores"), ("percent", "Percentages")),
               SAC: (("percent", "Percentage"), ("performance", "Performance"))}
_EXAM = re.compile(r"\bexam(?:s|inations?)?\b", re.I)
_YEAR_WORD = re.compile(r"\b(?:Yr|Year)\s*(\d{1,2})\b", re.I)
_YEAR_PREFIX = re.compile(r"^\s*(\d{1,2})(?=[A-Za-z\s])")   # subject codes such as "10MATEA" or "11 Applied Computing"
FIRST_SENIOR_YEAR = 11

# VCE SAC performance results, lowest to highest. These are ranks, not percentages.
SAC_BANDS = ("Very Low", "Low", "Medium", "Medium - High", "High", "High - Excellent")
PERFORMANCE_BANDS = ("Very Low", "Low", "Medium", "Medium - High", "High", "Very High", "High - Excellent", "Excellent")
_BAND_RANK = {b.lower(): i for i, b in enumerate(PERFORMANCE_BANDS)}
_NOT_PERFORMANCE = re.compile(r"effort|work habit|behaviou?r|progress", re.I)
_DASH = re.compile(r"\s*[-–—]\s*")
_LEVEL_LABEL = re.compile(r"level|standard|expected", re.I)


def _first(t: dict, kind: str) -> Score | None:
    for g in sorted(t.get("grades", []), key=lambda g: not g.get("isPrimary")):
        s = score(g)
        if s and s.kind == kind:
            return s
    return None


def year_level(t: dict) -> int | None:
    """The task's year level: the digits starting its class code (e.g. "10MATEA" is 10), or else "Yr10". None when neither says."""
    texts = (t.get("className") or "", t.get("subject") or "")
    for pattern in (_YEAR_PREFIX.match, _YEAR_WORD.search):
        for text in texts:
            m = pattern(text)
            if m:
                return int(m.group(1))
    return None


def performance_band(g: dict) -> Score | None:
    """A SAC performance result (e.g. "High - Excellent") as a rank, or None for any other row."""
    if g.get("isComment") or _NOT_PERFORMANCE.search(f"{g.get('item') or ''} {g.get('scheme') or ''}"):
        return None
    rank = _BAND_RANK.get(_DASH.sub(" - ", str(g.get("display") or "").strip()).lower())
    return None if rank is None else Score(rank, "performance", PERFORMANCE_BANDS[rank])


def _first_band(t: dict) -> Score | None:
    for g in sorted(t.get("grades", []), key=lambda g: not g.get("isPrimary")):
        s = performance_band(g)
        if s:
            return s
    return None


def performance_scale(labels) -> list[str]:
    """The bands to draw on a graph: the standard VCE ones plus any others in use, lowest first."""
    used = set(labels)
    return [b for b in PERFORMANCE_BANDS if b in SAC_BANDS or b in used]


def is_senior(t: dict) -> bool:
    """Year 11 and above. The class code decides, so a Year 10 student's VCE subject counts as senior.

    Without a year level, a VCE number score means Year 10 or below.
    """
    level = year_level(t)
    return level >= FIRST_SENIOR_YEAR if level is not None else _first(t, "number") is None


def mark_category(t: dict) -> str | None:
    """Puts each task in exactly one marks category.

    Any year: a marked task with the word "exam" in its name is an Exam.
    Year 10 and below: a number score or a percentage makes it a CAT.
    Year 11 and above: a percentage makes it a SAC, a number makes it a VCE Number Score,
    and a SAC performance result on its own makes it a SAC.
    """
    percent, number = _first(t, "percent"), _first(t, "number")
    senior = is_senior(t)
    if not (percent or number or (senior and _first_band(t))):
        return None
    if _EXAM.search(t.get("name") or ""):
        return EXAM
    if not senior:
        return CAT
    return SAC if percent or not number else VC


def score_types(tasks: list[dict]) -> list[str]:
    """The marks categories present: VCE Number Scores, CATs, SACs and Exams."""
    present = {mark_category(t) for t in tasks}
    return [k for k in SCORE_KINDS if k in present]


def task_score(t: dict, score_type: str, view: str | None = None) -> Score | None:
    """The task's mark in that category (None when the task belongs to another category).

    `view` picks which of the category's marks: "number", "percent" or "performance".
    """
    if mark_category(t) != score_type:
        return None
    kind = view or SCORE_KINDS[score_type][0]
    return _first_band(t) if kind == "performance" else _first(t, kind)


def headline(t: dict) -> str | None:
    """The task's main grade. In Year 10 and below, a number score goes ahead of a percentage."""
    primary = t.get("primaryGrade")
    if primary and not is_senior(t):
        row = next((g for g in t.get("grades", []) if g.get("display") == primary), {"display": primary})
        s, number = score(row), _first(t, "number")
        if s and s.kind == "percent" and number:
            return number.label
    return primary


PERFORMANCE_CATEGORIES = re.compile(r"assess|assign", re.I)


def counts_for_performance(t: dict) -> bool:
    """Only Assessments and Assignments are graphed."""
    return bool(PERFORMANCE_CATEGORIES.search(t.get("category") or ""))


LEVELS = [(100, "Well above"), (75, "Above"), (50, "At"), (25, "Towards"), (0, "Below")]


def level_results(t: dict) -> list[Score]:
    """The task's expected-level rows (e.g. Performance: "Above the expected level")."""
    return [s for s in map(score, t.get("grades", [])) if s and s.kind == "scheme" and _LEVEL_LABEL.search(s.label)]


def task_level(t: dict) -> str | None:
    """The task's expected-level band (Below, Towards, At, Above or Well above)."""
    results = level_results(t)
    return next(name for v, name in LEVELS if results[0].value >= v) if results else None


def has_score_type(t: dict, score_type: str) -> bool:
    if score_type == "Has rubric":
        return bool(t.get("rubrics"))
    if score_type == "Has feedback comment":
        return any(g.get("isComment") and g.get("display") for g in t.get("grades", []))
    return mark_category(t) == score_type


# ── planner: your own items, hidden tasks and "mark as done" ────────
@dataclass
class Planner:
    path: Path | None = None
    done: set = field(default_factory=set)        # task ids you marked done
    hidden: set = field(default_factory=set)      # task ids removed from the timeline
    items: list[dict] = field(default_factory=list)   # {id, title, due, subject, notes, done}

    @classmethod
    def load(cls, root: Path | None) -> "Planner":
        p = Path(root) / ".planner.json" if root else None
        try:
            raw = json.loads(p.read_text(encoding="utf-8")) if p else {}
        except (OSError, ValueError):
            raw = {}
        return cls(p, set(raw.get("done", [])), set(raw.get("hidden", [])), list(raw.get("items", [])))

    def save(self) -> None:
        if not self.path:
            return
        data = {"done": sorted(self.done, key=str), "hidden": sorted(self.hidden, key=str), "items": self.items}
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def add(self, title: str, due: str, subject: str = "", notes: str = "") -> dict:
        item = {"id": "my-" + uuid.uuid4().hex[:10], "title": title, "due": due, "subject": subject, "notes": notes, "done": False}
        self.items.append(item)
        self.save()
        return item

    def update(self, item_id: str, **changes) -> None:
        for it in self.items:
            if it["id"] == item_id:
                it.update(changes)
        self.save()

    def remove(self, item_id) -> None:
        """Deletes one of your items, or hides a Compass task from the timeline."""
        before = len(self.items)
        self.items = [it for it in self.items if it["id"] != item_id]
        if len(self.items) == before:
            self.hidden.add(item_id)
        self.save()

    def toggle_done(self, item_id) -> None:
        for it in self.items:
            if it["id"] == item_id:
                it["done"] = not it.get("done")
                self.save()
                return
        self.done.symmetric_difference_update({item_id})
        self.save()


@dataclass
class Entry:
    id: object
    title: str
    subject: str
    due: datetime | None
    status: str
    kind: str                # "compass" or "mine"
    task: dict | None = None
    item: dict | None = None
    hidden: bool = False


def timeline(tasks: list[dict], planner: Planner, at: datetime | None = None) -> list[Entry]:
    at = at or now()
    out = []
    for t in tasks:
        out.append(Entry(t.get("id"), t.get("name") or "", t.get("subject") or "", parse_dt(t.get("dueDate")),
                         status(t, planner.done, at), "compass", task=t, hidden=t.get("id") in planner.hidden))
    for it in planner.items:
        due = parse_dt(it.get("due"))
        st = "done" if it.get("done") else (status({"dueDate": it.get("due")}, None, at))
        out.append(Entry(it["id"], it.get("title") or "", it.get("subject") or "", due, st, "mine", item=it))
    far = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(out, key=lambda e: (e.due or far, e.title))


def bucket(e: Entry, at: datetime | None = None) -> str:
    """Timeline group for an entry."""
    at = (at or now()).astimezone()
    if not e.due:
        return "No due date"
    d = e.due.astimezone()
    today = at.replace(hour=0, minute=0, second=0, microsecond=0)
    if d < today:
        return "Overdue" if not is_complete(e.status) else "Earlier"
    if d < today + timedelta(days=1):
        return "Today"
    if d < today + timedelta(days=2):
        return "Tomorrow"
    week_end = today + timedelta(days=7 - today.weekday())
    if d < week_end:
        return "This week"
    if d < week_end + timedelta(days=7):
        return "Next week"
    if d < today + timedelta(days=31):
        return "Later this month"
    return "Later"


BUCKETS = ["Overdue", "Today", "Tomorrow", "This week", "Next week", "Later this month", "Later", "No due date", "Earlier"]


def to_ics(entries: list[Entry], host: str = "compass") -> str:
    """An iCalendar file of the entries' due dates (import into Google, Apple or Outlook calendars)."""
    def esc(s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Compass Scraper//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:Compass due dates"]
    for e in entries:
        if not e.due:
            continue
        start = e.due.astimezone(timezone.utc)
        lines += ["BEGIN:VEVENT", f"UID:{e.id}@{host}", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{start + timedelta(minutes=30):%Y%m%dT%H%M%SZ}",
                  f"SUMMARY:{esc(('Due: ' if e.kind == 'compass' else '') + e.title)}",
                  f"DESCRIPTION:{esc(e.subject + ' · ' + status_label(e.status))}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


# ── search ───────────────────────────────────────────────────────────
_KEYS = {"status": "status", "is": "status", "subject": "subject", "sub": "subject", "year": "year",
         "type": "type", "has": "type", "category": "category", "cat": "category"}
_TOKEN = re.compile(r'(\w+):"([^"]*)"|(\w+):(\S+)|"([^"]*)"|(\S+)')


@dataclass
class Query:
    words: list[str] = field(default_factory=list)
    filters: dict[str, list[str]] = field(default_factory=dict)


def parse_query(text: str) -> Query:
    """Free text plus optional filters, e.g.  essay status:graded subject:english has:rubric"""
    q = Query()
    for m in _TOKEN.finditer(text or ""):
        key, val = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4)) if m.group(3) else (None, None)
        if key and key.lower() in _KEYS:
            q.filters.setdefault(_KEYS[key.lower()], []).append(val.lower())
        else:
            word = m.group(5) or m.group(6) or (f"{key}:{val}" if key else "")
            if word:
                q.words.append(word.lower())
    return q


def _status_matches(st: str, wanted: str) -> bool:
    wanted = re.sub(r"[\s_-]", "", wanted)
    for name, keys in STATUS_FILTERS.items():
        if name.lower().replace(" ", "").startswith(wanted) and st in keys:
            return True
    return status_label(st).lower().replace(" ", "").startswith(wanted)


def haystack(t: dict) -> str:
    return json.dumps([t.get("name"), t.get("subject"), t.get("category"), t.get("className"),
                       [g.get("display") for g in t.get("grades", [])], t.get("descriptionText"),
                       [f.get("fileName") for k in ("attachments", "submissions") for f in t.get(k) or []]], ensure_ascii=False).lower()


def matches(t: dict, q: Query, st: str, is_new: bool = False) -> bool:
    for key, vals in q.filters.items():
        for v in vals:
            if key == "status":
                if v in ("new", "unread"):
                    if not is_new:
                        return False
                elif not _status_matches(st, v):
                    return False
            elif key == "subject" and v not in (t.get("subject") or "").lower():
                return False
            elif key == "year" and v not in (t.get("year") or "").lower():
                return False
            elif key == "category" and v not in (t.get("category") or "").lower():
                return False
            elif key == "type":
                names = [g.get("item", "").lower() for g in t.get("grades", []) if g.get("display")]
                if v == "rubric" and not t.get("rubrics"):
                    return False
                if v in ("comment", "feedback") and not any(g.get("isComment") and g.get("display") for g in t.get("grades", [])):
                    return False
                if v in ("file", "files", "submission") and not t.get("submissions"):
                    return False
                if v not in ("rubric", "comment", "feedback", "file", "files", "submission") and not any(v in n for n in names):
                    return False
    if q.words:
        hay = haystack(t)
        return all(w in hay for w in q.words)
    return True
