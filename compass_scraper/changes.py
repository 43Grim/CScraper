"""What changed since the last sync: new tasks, results, feedback, rubric marks and files.

Each task keeps a list of change entries (`task["changes"]`) that carries over from
sync to sync, so nothing is lost if you sync twice before looking. The app marks
entries as seen in `.seen.json` in the portfolio folder once you open the task.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

MAX_PER_TASK = 30
FILE_KINDS = {"attachments": "attachment", "submissions": "submission", "teacherResponses": "teacher response"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_previous(out: Path) -> dict | None:
    p = out / "data.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _grades(t: dict) -> dict[str, dict]:
    return {g.get("item") or "": g for g in t.get("grades", [])}


def _awarded(t: dict) -> dict[str, str | None]:
    return {f"{r.get('name')}|{c.get('criterion')}": c.get("awarded") for r in t.get("rubrics", []) for c in r.get("criteria", [])}


def task_changes(old: dict | None, new: dict) -> list[dict]:
    """Change entries for one task (empty when nothing changed)."""
    at = now_iso()
    out: list[dict] = []
    add = lambda key, kind, text: out.append({"key": key, "kind": kind, "text": text, "at": at})
    if old is None:
        add("task", "task", "New task")
        if any(g.get("display") for g in new.get("grades", [])):
            add("results", "result", "Results released")
        return out

    og, ng = _grades(old), _grades(new)
    for item, g in ng.items():
        before = (og.get(item) or {}).get("display") or ""
        after = g.get("display") or ""
        if after and after != before:
            kind = "feedback" if g.get("isComment") else "result"
            if before:
                add(f"grade:{item}:{after[:40]}", kind, f"{'Feedback' if kind == 'feedback' else item} updated")
            else:
                add(f"grade:{item}:{after[:40]}", kind, "New feedback" if kind == "feedback" else f"New result: {item}")

    if any(a and a != _awarded(old).get(k) for k, a in _awarded(new).items()):
        add("rubric:" + json.dumps(_awarded(new), sort_keys=True)[:80], "rubric", "Rubric marked")

    for key, label in FILE_KINDS.items():
        before = {f.get("id") for f in old.get(key) or []}
        for f in new.get(key) or []:
            if f.get("id") not in before:
                add(f"file:{key}:{f.get('id')}", "file", f"New {label}: {f.get('fileName') or f.get('name')}")

    if (old.get("dueDate") or "") != (new.get("dueDate") or "") and new.get("dueDate"):
        add(f"due:{new.get('dueDate')}", "due", "Due date changed")
    return out


def apply(previous: dict | None, tasks: list[dict]) -> dict:
    """Attaches `changes` to every task (carrying over earlier ones) and returns this sync's summary."""
    first = previous is None
    old_by_id = {t.get("id"): t for t in (previous or {}).get("tasks", [])}
    summary = {"at": now_iso(), "firstSync": first, "newTasks": 0, "newResults": 0, "newFeedback": 0,
               "newFiles": 0, "rubricsMarked": 0, "items": []}
    for t in tasks:
        old = old_by_id.get(t.get("id"))
        carried = list((old or {}).get("changes") or [])
        fresh = [] if first else task_changes(old, t)
        known = {c["key"] for c in carried}
        fresh = [c for c in fresh if c["key"] not in known]
        t["changes"] = (carried + fresh)[-MAX_PER_TASK:]
        for c in fresh:
            k = c["kind"]
            summary["newTasks"] += k == "task"
            summary["newResults"] += k == "result"
            summary["newFeedback"] += k == "feedback"
            summary["newFiles"] += k == "file"
            summary["rubricsMarked"] += k == "rubric"
            summary["items"].append({"taskId": t.get("id"), "task": t.get("name"), "subject": t.get("subject"), "text": c["text"]})
    return summary


def describe(summary: dict) -> str:
    if summary.get("firstSync"):
        return "First sync: everything is new."
    bits = []
    for key, one, many in (("newTasks", "new task", "new tasks"), ("newResults", "new result", "new results"),
                           ("newFeedback", "new piece of feedback", "new pieces of feedback"),
                           ("rubricsMarked", "rubric marked", "rubrics marked"), ("newFiles", "new file", "new files")):
        n = summary.get(key) or 0
        if n:
            bits.append(f"{n} {one if n == 1 else many}")
    return ", ".join(bits) if bits else "Nothing new since the last sync."


# ── seen markers (kept in the portfolio folder) ─────────────────────
def seen_path(out: Path) -> Path:
    return Path(out) / ".seen.json"


def load_seen(out: Path) -> set[str]:
    try:
        return set(json.loads(seen_path(out).read_text()))
    except (OSError, ValueError):
        return set()


def save_seen(out: Path, seen: set[str]) -> None:
    try:
        seen_path(out).write_text(json.dumps(sorted(seen)))
    except OSError:
        pass


def seen_key(t: dict, c: dict) -> str:
    return f"{t.get('id')}|{c['key']}"


def unseen(t: dict, seen: set[str]) -> list[dict]:
    return [c for c in t.get("changes") or [] if seen_key(t, c) not in seen]
