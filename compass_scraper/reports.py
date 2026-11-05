"""School reports: reads the "All Semester Reports" ZIP that Compass gives you.

Only four things are kept from each report, and nothing else:
  * Victorian Curriculum levels per learning area and strand (with the expected level band)
  * Learning behaviours per subject and term
  * Class attendance per subject
  * The teacher per subject
plus one copy of the "Learning Behaviour Data" guide table, saved as an image.

The extracted data is saved as <portfolio>/reports.json, so the ZIP isn't needed afterwards.
No Qt here, so the CLI and the tests can use it too.
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPORTS_FILE = "reports.json"
GUIDE_IMAGE = "learning-behaviour-guide.png"
REPORTS_DIR = "School Reports"      # inside the portfolio; holds the guide image
RATINGS = ("Needs Attention", "Inconsistent", "Good", "Very Good", "Excellent")   # lowest first
BEHAVIOURS = ("Agency in learning", "Completes required work", "Works productively",
              "Seeks assistance when necessary", "Works in a team", "Respects the rights of others to learn")
_BEHAVIOUR_KEYS = (("agency", 0), ("complete", 1), ("productiv", 2), ("assist", 3), ("team", 4), ("respect", 5))
_CYCLE = re.compile(r"^(?P<year>\d{4})\b.*?(?P<kind>Semester\s*(?P<sem>[12])|Term\s*(?P<term>[1-4]))", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}


class ReportError(Exception):
    """The file isn't a Compass reports ZIP (or PDF) that can be read."""


@dataclass
class Report:
    cycle: str                      # e.g. "2023 - Semester 1 Reports (June) 2023"
    year: int
    kind: str                       # "semester" or "learning behaviour"
    period: str                     # "Semester 1", "Term 3"
    month: int                      # month the report came out, for ordering
    year_level: str = ""            # "Year 7"
    curriculum: list[dict] = field(default_factory=list)   # {area, strand, level, expected: [lo, hi]}
    subjects: list[dict] = field(default_factory=list)     # {subject, teacher, attendance, behaviours: {name: {term: rating}}}

    @property
    def sort_key(self) -> tuple:
        return (self.year, self.month, self.period)

    @property
    def short(self) -> str:
        """A short column name, e.g. "2023 S1" or "2025 T3"."""
        p = self.period.split()
        return f"{self.year} {p[0][0]}{p[-1]}" if p else str(self.year)

    def to_json(self) -> dict:
        return {"cycle": self.cycle, "year": self.year, "kind": self.kind, "period": self.period, "month": self.month,
                "yearLevel": self.year_level, "curriculum": self.curriculum, "subjects": self.subjects}

    @classmethod
    def from_json(cls, d: dict) -> "Report":
        return cls(d["cycle"], int(d["year"]), d.get("kind", ""), d.get("period", ""), int(d.get("month") or 0),
                   d.get("yearLevel", ""), list(d.get("curriculum") or []), list(d.get("subjects") or []))


# ── reading one PDF ──────────────────────────────────────────────────
def _cycle_info(name: str) -> tuple[int, str, str, int]:
    m = _CYCLE.search(name)
    if not m:
        raise ReportError(f"Not a Compass report: {name}")
    period = f"Semester {m['sem']}" if m["sem"] else f"Term {m['term']}"
    kind = "learning behaviour" if re.search(r"learning\s+behaviou?r", name, re.I) else "semester"
    month = next((i for word, i in _MONTHS.items() if re.search(rf"\({word}\)", name, re.I)), 0)
    if not month:
        month = {"Semester 1": 6, "Semester 2": 12, "Term 1": 3, "Term 2": 6, "Term 3": 8, "Term 4": 11}[period]
    return int(m["year"]), kind, period, month


def behaviour_name(raw: str) -> str:
    """The six standard names, whatever wording a year's report used ("Learning Habits Agency in learning",
    "Works productively in class", ...). Unknown names are kept as they are."""
    low = raw.lower()
    return next((BEHAVIOURS[i] for key, i in _BEHAVIOUR_KEYS if key in low), raw.strip())


def _lines(page) -> list[str]:
    return [ln.strip() for ln in (page.extract_text() or "").splitlines() if ln.strip()]


def _is_filled(color) -> bool:
    """A coloured (not white, not header grey) fill: a learning behaviour bar."""
    if color is None:
        return False
    vals = color if isinstance(color, (list, tuple)) else (color,)
    try:
        vals = [float(v) for v in vals]
    except (TypeError, ValueError):
        return False
    if all(v > 0.97 for v in vals):             # white
        return False
    if len(set(round(v, 2) for v in vals)) == 1 and vals[0] > 0.7:   # light grey header
        return False
    return True


def _rgb(color) -> tuple:
    vals = color if isinstance(color, (list, tuple)) else (color,)
    return tuple(round(float(v), 2) for v in vals)


def _curriculum(page) -> list[dict]:
    """The Victorian Curriculum chart: one row per strand, a dot for this semester's level."""
    from pdfminer.pdftypes import resolve1

    words = page.extract_words()
    heads = [(w, words[i + 1]) for i, w in enumerate(words[:-1])
             if w["text"] == "Level" and re.fullmatch(r"\d{1,2}", words[i + 1]["text"])
             and not (i and words[i - 1]["text"] == "Beyond")]
    if len(heads) < 2:
        return []
    centres = sorted(((a["x0"] + b["x1"]) / 2, int(b["text"])) for a, b in heads)
    (c0, l0), (c1, l1) = centres[0], centres[-1]
    width = (c1 - c0) / ((l1 - l0) or 1)               # page units per level
    edge0 = c0 - width / 2                              # left edge of the first level column
    header_bottom = max(b["bottom"] for _, b in heads)

    def level_at(x: float) -> float:
        # Compass's convention: the "Level 7" column runs from 7.0 at its left edge to 8.0 at its right edge,
        # so a dot in the middle is 7.5. Anything past the last column is "Beyond Level N".
        return round((l0 + (x - edge0) / width) * 2) / 2

    # dot images: each row is split into half-level cells; a dot straddles the cells it touches
    rows: dict[int, list] = {}
    for im in page.images:
        if im["top"] < header_bottom or im["width"] > width:
            continue
        try:
            mask = resolve1(im["stream"].attrs.get("SMask"))
            alpha = mask.get_data() if mask is not None else im["stream"].get_data()
            w, h = int(mask.attrs["Width"]), int(mask.attrs["Height"])
        except Exception:
            continue
        if len(alpha) < w * h:
            continue
        rows.setdefault(round(im["top"]), []).append((im, alpha, w, h))

    yellow = [r for r in page.rects if r.get("fill") and _rgb(r.get("non_stroking_color"))[:3] == (1.0, 0.88, 0.0)]
    labels = [w for w in words if w["top"] > header_bottom]
    out, area = [], ""
    # learning areas sit further left than their strands
    left = min((w["x0"] for w in labels), default=0)
    lines: dict[int, list] = {}
    for w in labels:
        lines.setdefault(round(w["top"]), []).append(w)
    for top, ws in sorted(lines.items()):
        ws.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws if w["x1"] < c0 - width / 2)
        if not text or text.startswith("Legend"):
            if text.startswith("Legend"):
                break
            continue
        row = next((v for k, v in rows.items() if abs(k - top) < 8), None)
        if row is None:
            if ws[0]["x0"] <= left + 2:
                area = text
            continue
        # column-wise alpha → x positions of dot ink; split into blobs (current dot, previous ring)
        ink: list[tuple[float, float, bool]] = []   # (x, weight, centre is solid)
        for im, alpha, w, h in row:
            for col in range(w):
                total = sum(alpha[r * w + col] for r in range(0, h, 4))
                if total:
                    centre = alpha[(h // 2) * w + col]
                    ink.append((im["x0"] + (col + 0.5) / w * im["width"], total, centre))
        ink.sort()
        blobs, cur = [], []
        for x, wt, c in ink:
            if cur and x - cur[-1][0] > 1.5:
                blobs.append(cur)
                cur = []
            cur.append((x, wt, c))
        if cur:
            blobs.append(cur)
        level = None
        for b in blobs:
            cx = sum(x * wt for x, wt, _ in b) / sum(wt for _, wt, _ in b)
            # the filled dot (this semester) is solid at its centre; the "previous result" ring is hollow
            mid = min(b, key=lambda p: abs(p[0] - cx))
            if mid[2] > 128:
                level = level_at(cx)
        band = [r for r in yellow if abs(r["top"] - top) < 12]
        expected = [level_at(min(r["x0"] for r in band)), level_at(max(r["x1"] for r in band))] if band else None
        out.append({"area": area, "strand": text, "level": level, "expected": expected, "beyond": l1 + 1})
    return out


def _subject_blocks(page) -> list[dict]:
    """Subject pages: teacher, class attendance and the learning behaviour bars, nothing else."""
    words = page.extract_words(keep_blank_chars=False)
    starts = [w for w in words if w["text"] == "Teacher:"]
    out = []
    for i, t in enumerate(starts):
        top, bottom = t["top"] - 4, (starts[i + 1]["top"] - 4 if i + 1 < len(starts) else page.height)
        block = page.within_bbox((0, max(0, top), page.width, bottom))
        lines = _lines(block)
        if len(lines) < 3 or lines[0] != "Teacher:":
            continue
        subject, teacher = lines[1], lines[2]
        att = next((re.search(r"(\d+(?:\.\d+)?)\s*$", ln) for ln in lines if ln.startswith("School Attendance")), None)
        entry = {"subject": subject, "teacher": teacher, "attendance": float(att.group(1)) if att else None,
                 "behaviours": _behaviours(block)}
        out.append(entry)
    return out


def _behaviours(block) -> dict:
    words = block.extract_words()
    axis = {w["text"]: w for w in words if w["text"] in ("Excellent", "Good", "Inconsistent")}
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w["top"]), []).append(w)
    # rating labels may be two words ("Very Good", "Needs Attention"); find each label's vertical centre
    label_y = {}
    for top, ws in lines.items():
        text = " ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"]))
        if text in RATINGS:
            label_y[text] = (ws[0]["top"] + ws[0]["bottom"]) / 2
    term_line = next((sorted(ws, key=lambda w: w["x0"]) for top, ws in lines.items()
                      if sorted(ws, key=lambda w: w["x0"])[0]["text"] == "Term"), None)
    if not term_line or len(label_y) < 2 or not axis:
        return {}
    terms = [(w["x0"] + w["x1"]) / 2 for w in term_line[1:]]
    term_names = [w["text"] for w in term_line[1:]]
    head_top = min(label_y.values()) - 60
    learn = next((w for w in words if w["text"] == "Behaviours"), None)
    if learn:
        head_top = learn["bottom"]
    # behaviour names: the header words above the chart, grouped by the bar columns under them
    per = 0
    for n in range(1, len(terms) + 1):
        if len(terms) % n == 0 and len(set(term_names[:n])) == n and term_names[:n] * (len(terms) // n) == term_names:
            per = n
            break
    per = per or 1
    groups = [terms[i:i + per] for i in range(0, len(terms), per)]
    centres = [sum(g) / len(g) for g in groups]
    header = [w for w in words if head_top < w["top"] < min(label_y.values()) - 6]
    names = [[] for _ in groups]
    for w in header:
        cx = (w["x0"] + w["x1"]) / 2
        k = min(range(len(centres)), key=lambda i: abs(centres[i] - cx))
        names[k].append(w)
    names = [behaviour_name(" ".join(w["text"] for w in sorted(ws, key=lambda w: (round(w["top"]), w["x0"]))))
             or f"Behaviour {i + 1}" for i, ws in enumerate(names)]
    bars = [r for r in block.rects if r.get("fill") and _is_filled(r.get("non_stroking_color"))
            and r["top"] > min(label_y.values()) - 30]
    ordered = sorted(label_y.items(), key=lambda kv: kv[1])     # top (Excellent) first
    out: dict[str, dict[str, str]] = {}
    for gi, g in enumerate(groups):
        for j, x in enumerate(g):
            mine = [r for r in bars if r["x0"] - 2 <= x <= r["x1"] + 2]
            if not mine:
                continue
            top = min(r["top"] for r in mine)
            rating = min(ordered, key=lambda kv: abs(kv[1] - top))[0]
            out.setdefault(names[gi], {})[term_names[gi * per + j]] = rating
    return out


def read_pdf(data: bytes, name: str, guide_out: Path | None = None) -> Report:
    """Reads one report PDF. If guide_out is given and the PDF has the Learning Behaviour Data table,
    that table is saved there as a PNG (once)."""
    import pdfplumber

    year, kind, period, month = _cycle_info(name)
    rep = Report(re.sub(r"\.pdf$", "", Path(name).name, flags=re.I), year, kind, period, month)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            lines = _lines(page)
            if not lines:
                continue
            if not rep.year_level:
                yl = next((ln for ln in lines[:12] if re.fullmatch(r"Year\s+\d{1,2}", ln)), "")
                rep.year_level = yl
            if lines[0].startswith("Learning Behaviour Data"):
                if guide_out is not None and not guide_out.exists() and page.images:
                    img = max(page.images, key=lambda i: i["width"] * i["height"])
                    bbox = (max(0, img["x0"]), max(0, img["top"]), min(page.width, img["x1"]), min(page.height, img["bottom"]))
                    try:
                        guide_out.parent.mkdir(parents=True, exist_ok=True)
                        tmp = guide_out.with_suffix(".tmp.png")
                        page.crop(bbox).to_image(resolution=150).save(str(tmp))
                        os.replace(tmp, guide_out)
                    except Exception:
                        pass
                continue
            if lines[0] == "Victorian Curriculum":
                rep.curriculum += _curriculum(page)
                continue
            if "Teacher:" in lines:
                rep.subjects += _subject_blocks(page)
    return rep


# ── the store: reports.json in the portfolio ─────────────────────────
@dataclass
class ReportStore:
    root: Path | None
    reports: list[Report] = field(default_factory=list)
    imported: str = ""

    @property
    def path(self) -> Path | None:
        return Path(self.root) / REPORTS_FILE if self.root else None

    @property
    def guide(self) -> Path | None:
        p = Path(self.root) / REPORTS_DIR / GUIDE_IMAGE if self.root else None
        return p if p and p.exists() else None

    @classmethod
    def load(cls, root: Path | None) -> "ReportStore":
        store = cls(Path(root) if root else None)
        try:
            raw = json.loads(store.path.read_text(encoding="utf-8")) if store.path else {}
        except (OSError, ValueError):
            raw = {}
        store.reports = sorted((Report.from_json(r) for r in raw.get("reports", [])), key=lambda r: r.sort_key)
        store.imported = raw.get("imported", "")
        return store

    def save(self) -> None:
        if not self.path:
            return
        data = {"version": 1, "imported": self.imported, "reports": [r.to_json() for r in self.reports]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".reports-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def import_zip(self, path: str | Path, log=lambda msg: None) -> tuple[int, int]:
        """Reads every report PDF in the ZIP (or a single PDF), replacing reports with the same cycle.
        HeadStart reports are skipped. Returns (reports read, PDFs skipped)."""
        path = Path(path)
        guide = Path(self.root) / REPORTS_DIR / GUIDE_IMAGE if self.root else None
        files: list[tuple[str, bytes]] = []
        if path.suffix.lower() == ".pdf":
            files.append((path.name, path.read_bytes()))
        else:
            try:
                with zipfile.ZipFile(path) as z:
                    for info in z.infolist():
                        if info.filename.lower().endswith(".pdf") and not info.is_dir():
                            files.append((Path(info.filename).name, z.read(info)))
            except zipfile.BadZipFile as e:
                raise ReportError(f"{path.name} isn't a ZIP file.") from e
        if not files:
            raise ReportError(f"No report PDFs found in {path.name}.")
        got, skipped = {}, 0
        for name, data in sorted(files):
            if re.search(r"head\s*start", name, re.I):
                skipped += 1
                continue
            try:
                rep = read_pdf(data, name, guide)
            except ReportError:
                skipped += 1
                log(f"Skipped {name}: not a Compass report")
                continue
            except Exception as e:      # a damaged or unusual PDF shouldn't stop the rest
                skipped += 1
                log(f"Skipped {name}: {e}")
                continue
            got[rep.cycle] = rep
            log(f"Read {rep.cycle}")
        if not got:
            raise ReportError("None of the PDFs in that file could be read as Compass reports.")
        keep = [r for r in self.reports if r.cycle not in got]
        self.reports = sorted(keep + list(got.values()), key=lambda r: r.sort_key)
        self.imported = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.save()
        return len(got), skipped

    def clear(self) -> None:
        self.reports = []
        self.save()

    # summaries used by the Reports page
    def semester_reports(self) -> list[Report]:
        return [r for r in self.reports if r.curriculum]

    def strands(self) -> list[tuple[str, str]]:
        seen: dict[tuple[str, str], None] = {}
        for r in self.semester_reports():
            for c in r.curriculum:
                seen.setdefault((c["area"], c["strand"]), None)
        return list(seen)

    def behaviour_names(self) -> list[str]:
        seen: dict[str, None] = {b: None for b in BEHAVIOURS if any(
            b in s.get("behaviours", {}) for r in self.reports for s in r.subjects)}
        for r in self.reports:
            for s in r.subjects:
                for name in s.get("behaviours", {}):
                    seen.setdefault(name, None)
        return list(seen)


def rating_value(rating: str | None) -> int | None:
    """Needs Attention = 1 … Excellent = 5."""
    return RATINGS.index(rating) + 1 if rating in RATINGS else None


def latest_ratings(subject: dict) -> dict[str, str]:
    """Each behaviour's rating in the latest term of that report."""
    out = {}
    for name, terms in (subject.get("behaviours") or {}).items():
        if terms:
            out[name] = terms[max(terms, key=lambda t: (len(t), t))]
    return out
