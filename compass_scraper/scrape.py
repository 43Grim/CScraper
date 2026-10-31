"""Collects every learning task for the chosen years, then downloads the files."""
from __future__ import annotations

import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import changes
from .client import CompassClient, CompassError, SessionExpired
from .model import Lookups, normalise_task
from .report import render_rubric_page, write_dashboard

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(s: str | None, limit: int = 80) -> str:
    s = _BAD.sub("_", (s or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")
    return (s[:limit].rstrip(" .") or "untitled")


class Cancelled(Exception):
    """The user pressed Stop. Files already downloaded are kept, so a re-run resumes."""


@dataclass
class Progress:
    """Callbacks the CLI and GUI use to drive their live display. All optional."""
    phase: Callable[[str], None] = lambda msg: None
    tasks_total: Callable[[int], None] = lambda n: None
    task_done: Callable[[str], None] = lambda name: None
    files_total: Callable[[int], None] = lambda n: None
    file_done: Callable[[str, bool, str | None], None] = lambda name, ok, err: None
    log: Callable[[str], None] = lambda msg: None
    should_stop: Callable[[], bool] = lambda: False

    def check(self) -> None:
        if self.should_stop():
            raise Cancelled()


@dataclass
class Result:
    out_dir: Path
    tasks: list[dict] = field(default_factory=list)
    files_ok: int = 0
    files_skipped: int = 0
    files_failed: list[dict] = field(default_factory=list)
    zip_path: Path | None = None
    changes: dict = field(default_factory=dict)


def pick_years(groups: list[dict], wanted: list[str] | None) -> list[dict]:
    """`wanted` holds names, import identifiers (e.g. "2025") or ids; empty means every year."""
    if not wanted:
        return groups
    w = {x.strip().lower() for x in wanted}
    chosen = [g for g in groups if {str(g.get("id")), str(g.get("importIdentifier") or "").lower(), str(g.get("name") or "").lower()} & w]
    if not chosen:
        names = ", ".join(str(g.get("importIdentifier") or g.get("name")) for g in groups)
        raise CompassError(f"No academic year matches {wanted}. Available: {names}")
    return chosen


def collect(client: CompassClient, years: list[str] | None, progress: Progress, include_hidden: bool = False) -> tuple[list[dict], dict]:
    progress.phase("Loading reference data")
    groups = client.academic_groups()
    chosen = pick_years(groups, years)
    try:
        schemes = client.grading_schemes()
    except CompassError as e:  # labels are nice-to-have; raw grades still come through
        progress.log(f"Could not load grading schemes ({e}); grades will show raw values.")
        schemes = []
    try:
        categories = client.task_categories()
    except CompassError as e:
        progress.log(f"Could not load task categories ({e}).")
        categories = []

    raw: list[tuple[dict, dict]] = []
    for g in chosen:
        progress.phase(f"Listing tasks for {g.get('name')}")
        for task, total in client.iter_learning_tasks(int(g["id"]), include_hidden=include_hidden):
            raw.append((task, g))
            progress.check()
        progress.log(f"{g.get('name')}: {sum(1 for _, y in raw if y is g)} tasks")

    progress.phase("Loading rubrics")
    wiki_ids = {w for t, _ in raw for w in (t.get("rubricWikiNodeIds") or [])}
    rubrics = client.rubrics_by_wiki_node_ids(wiki_ids) if wiki_ids else []
    lk = Lookups.build(schemes, categories, rubrics)

    tasks = [normalise_task(t, g, lk, client.session.user_id) for t, g in raw]
    meta = {"academicGroups": groups, "gradingSchemes": schemes, "categories": categories,
            "syncedYears": [g.get("id") for g in chosen]}
    return tasks, meta


def _task_dir(out: Path, t: dict) -> Path:
    return out / safe_name(t["year"]) / safe_name(t["subject"]) / f"{safe_name(t['name'], 70)} [{t['id']}]"


def _unique(name: str, used: set[str]) -> str:
    base, dot, ext = name.rpartition(".")
    if not dot:
        base, ext = name, ""
    cand, n = name, 2
    while cand.lower() in used:
        cand = f"{base} ({n}){dot}{ext}"
        n += 1
    used.add(cand.lower())
    return cand


def plan_files(client: CompassClient, out: Path, tasks: list[dict]) -> list[dict]:
    """Decides where every file goes and records the relative path on the task."""
    jobs = []
    for t in tasks:
        tdir = _task_dir(out, t)
        t["folder"] = tdir.relative_to(out).as_posix()
        groups = (
            ("attachments", "Attachments", lambda f: client.attachment_url(f["id"], f["fileName"] or f["name"])),
            ("submissions", "Submissions", lambda f: client.submission_url(t["id"], f["id"])),
            ("teacherResponses", "Teacher responses", lambda f: client.teacher_response_url(t["id"], f["id"])),
        )
        for key, sub, url_for in groups:
            used: set[str] = set()
            for f in t[key]:
                if not f.get("fileName") and f.get("contentUrl"):
                    f["link"] = f["contentUrl"]  # a URL submission, nothing to download
                    continue
                if f.get("id") is None:
                    continue
                name = _unique(safe_name(f.get("fileName") or f.get("name") or f"file-{f['id']}", 120), used)
                dest = tdir / sub / name
                f["path"] = dest.relative_to(out).as_posix()
                jobs.append({"task": t["name"], "kind": key, "url": url_for(f), "dest": dest, "file": f})
    return jobs


def download_all(client: CompassClient, jobs: list[dict], progress: Progress, workers: int = 4) -> tuple[int, int, list[dict]]:
    ok = skipped = 0
    failed: list[dict] = []
    progress.files_total(len(jobs))

    def run(job):
        progress.check()
        dest: Path = job["dest"]
        if dest.exists() and dest.stat().st_size > 0:
            return job, "skipped", None
        size = client.download(job["url"], dest)
        job["file"]["size"] = size
        return job, "ok", None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run, j): j for j in jobs}
        for fut in as_completed(futures):
            try:
                job, status, _ = fut.result()
                if status == "skipped":
                    skipped += 1
                else:
                    ok += 1
                progress.file_done(job["dest"].name, True, None)
            except (SessionExpired, Cancelled):
                for f in futures:
                    f.cancel()
                raise
            except Exception as e:  # keep going; report at the end
                job = futures[fut]
                job["file"]["error"] = str(e)
                failed.append({"task": job["task"], "file": job["dest"].name, "error": str(e)})
                progress.file_done(job["dest"].name, False, str(e))
    return ok, skipped, failed


def write_outputs(out: Path, tasks: list[dict], meta: dict, student: dict, last_sync: dict | None = None) -> None:
    for t in tasks:
        tdir = out / t["folder"]
        tdir.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        for i, rub in enumerate(t["rubrics"]):
            p = tdir / _unique(f"Rubric - {safe_name(rub['name'] or str(i + 1), 60)}.html", used)
            p.write_text(render_rubric_page(t, rub), encoding="utf-8")
            rub["path"] = p.relative_to(out).as_posix()
        (tdir / "task.json").write_text(json.dumps(t, indent=1, ensure_ascii=False), encoding="utf-8")
    data = {"student": student, "tasks": tasks, **meta, "lastSync": last_sync or {}}
    tmp = out / "data.json.part"
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out / "data.json")
    write_dashboard(out / "index.html", tasks, student)


def make_zip(out: Path) -> Path:
    zip_path = out.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file() and not p.name.endswith(".part"):
                z.write(p, p.relative_to(out.parent).as_posix())
    return zip_path


def run(client: CompassClient, out: Path, years: list[str] | None = None, progress: Progress | None = None,
        download: bool = True, zip_output: bool = True, include_hidden: bool = False, workers: int = 4) -> Result:
    progress = progress or Progress()
    out.mkdir(parents=True, exist_ok=True)
    previous = changes.load_previous(out)
    tasks, meta = collect(client, years, progress, include_hidden=include_hidden)
    progress.tasks_total(len(tasks))
    for t in tasks:
        progress.task_done(t["name"])
    res = Result(out_dir=out, tasks=tasks)

    jobs = plan_files(client, out, tasks)
    if download and jobs:
        progress.phase("Downloading files")
        res.files_ok, res.files_skipped, res.files_failed = download_all(client, jobs, progress, workers=workers)

    progress.check()
    progress.phase("Writing portfolio")
    res.changes = changes.apply(previous, tasks)
    # Years not synced this time stay in the portfolio as they were.
    synced = set(meta["syncedYears"])
    kept = [t for t in (previous or {}).get("tasks", []) if t.get("academicGroupId") not in synced]
    all_tasks = tasks + kept
    student = {"name": client.session.user_name, "userId": client.session.user_id, "host": client.session.host}
    write_outputs(out, all_tasks, meta, student, res.changes)
    progress.log(changes.describe(res.changes))
    if zip_output:
        progress.phase("Building ZIP")
        res.zip_path = make_zip(out)
    progress.phase("Done")
    return res
