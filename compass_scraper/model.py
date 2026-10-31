"""Turns raw Compass API responses into a clean, self-describing task record.

Field names follow what was observed with the site mapper (see
compass-mapper/compass-api-findings.md).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field


@dataclass
class Lookups:
    grade_options: dict[str, dict] = field(default_factory=dict)   # reportGradingSchemeOptionId -> option
    categories: dict[int, dict] = field(default_factory=dict)      # categoryId -> category
    rubrics_by_wiki_node: dict[int, dict] = field(default_factory=dict)

    @classmethod
    def build(cls, grading_schemes: list[dict], categories: list[dict], rubrics: list[dict]) -> "Lookups":
        opts = {}
        for scheme in grading_schemes or []:
            for opt in scheme.get("options") or []:
                if opt.get("id") is not None:
                    opts[str(opt["id"])] = {**opt, "schemeName": scheme.get("name")}
        cats = {c["categoryId"]: c for c in categories or [] if c.get("categoryId") is not None}
        rubs = {r["wikiNodeId"]: r for r in rubrics or [] if r.get("wikiNodeId") is not None}
        return cls(opts, cats, rubs)


_BR = re.compile(r"<br\s*/?>|</p>|</div>|</li>", re.I)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(s: str | None) -> str:
    """Plain text with line breaks kept (teacher comments are sometimes stored as HTML)."""
    if not s:
        return ""
    if "<" in s:
        s = _BR.sub("\n", s)
        s = _TAG.sub("", s)
    s = html.unescape(s).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def _is_comment_item(item: dict) -> bool:
    return item.get("commentType") is not None or "comment" in (item.get("name") or "").lower()


def grades_for(task: dict, student: dict, lk: Lookups) -> list[dict]:
    """One row per line of the Feedback tab's Grades table, in display order."""
    results = {r.get("taskGradingItemId"): r for r in student.get("results") or []}
    rows = []
    items = sorted(task.get("gradingItems") or [], key=lambda i: (i.get("ordinal") or 0, i.get("gradingItemOrderBy") or 0))
    for item in items:
        res = results.get(item.get("id")) or {}
        raw = res.get("result")
        opt = lk.grade_options.get(str(res.get("reportGradingSchemeOptionId"))) if res.get("reportGradingSchemeOptionId") else None
        is_comment = _is_comment_item(item)
        if is_comment:
            display = html_to_text(raw)
        elif opt and opt.get("displayValue") not in (None, ""):
            display = str(opt["displayValue"])
        else:
            display = "" if raw is None else str(raw)
        rows.append({
            "item": item.get("name"),
            "shortName": item.get("shortName"),
            "isPrimary": bool(item.get("isPrimaryGrade")),
            "isComment": is_comment,
            "value": raw,
            "display": display,
            "scheme": opt.get("schemeName") if opt else None,
            "colour": opt.get("colour") if opt else None,
            "modified": res.get("modifiedTimestamp"),
        })
    # Keep any result whose grading item isn't listed (shouldn't happen, but never drop feedback).
    listed = {i.get("id") for i in items}
    for gid, res in results.items():
        if gid not in listed and res.get("result") not in (None, ""):
            rows.append({"item": f"Grading item {gid}", "shortName": None, "isPrimary": False, "isComment": False,
                         "value": res.get("result"), "display": html_to_text(str(res.get("result"))),
                         "scheme": None, "colour": None, "modified": res.get("modifiedTimestamp")})
    return rows


def rubric_for(task: dict, student: dict, lk: Lookups) -> list[dict]:
    """Rubrics attached to the task, as criteria x columns with the awarded cells marked."""
    out = []
    awarded = {(r.get("rubricId"), r.get("rubricCriterionId")): r.get("rubricGradingScaleId")
               for r in student.get("rubricResults") or []}
    for wid in task.get("rubricWikiNodeIds") or []:
        rub = lk.rubrics_by_wiki_node.get(wid)
        if not rub:
            continue
        criteria = sorted(rub.get("criteria") or [], key=lambda c: c.get("ordinal") or 0)
        columns: list[str] = []
        rows = []
        for crit in criteria:
            scales = sorted(crit.get("gradingScales") or [], key=lambda s: s.get("ordinal") or 0)
            for s in scales:
                if s.get("name") not in columns:
                    columns.append(s.get("name"))
            chosen = awarded.get((rub.get("id"), crit.get("id")))
            rows.append({
                "criterion": crit.get("name"),
                "description": html_to_text(crit.get("description")),
                "cells": [{
                    "column": s.get("name"),
                    "points": [html_to_text(d.get("description")) for d in sorted(s.get("contentDescriptors") or [], key=lambda d: d.get("ordinal") or 0)],
                    "awarded": s.get("id") == chosen,
                } for s in scales],
                "awarded": next((s.get("name") for s in scales if s.get("id") == chosen), None),
            })
        out.append({"id": rub.get("id"), "name": rub.get("name"), "wikiNodeId": wid, "columns": columns, "criteria": rows})
    return out


def normalise_task(task: dict, year: dict, lk: Lookups, user_id: int) -> dict:
    students = task.get("students") or []
    student = next((s for s in students if s.get("userId") == user_id), students[0] if students else {})
    cat = lk.categories.get(task.get("categoryId")) or {}
    grades = grades_for(task, student, lk)
    primary = next((g for g in grades if g["isPrimary"] and g["display"]), None)
    return {
        "id": task.get("id"),
        "name": task.get("name"),
        "year": year.get("name"),
        "academicGroupId": year.get("id"),
        "subject": task.get("subjectName") or task.get("activityName") or "Unknown subject",
        "subjectId": task.get("subjectId"),
        "className": task.get("activityName"),
        "category": cat.get("categoryName"),
        "categoryColour": cat.get("categoryColour"),
        "dueDate": task.get("dueDateTimestamp") or student.get("dueDateTimestamp") or None,
        "created": task.get("createdTimestamp"),
        "descriptionHtml": task.get("description") or "",
        "descriptionText": html_to_text(task.get("description")),
        "submissionStatus": student.get("submissionStatus"),
        "submittedTimestamp": student.get("submittedTimestamp") or None,
        "primaryGrade": primary["display"] if primary else None,
        "grades": grades,
        "rubrics": rubric_for(task, student, lk),
        "attachments": [{"id": a.get("id"), "name": a.get("name") or a.get("fileName"), "fileName": a.get("fileName") or a.get("name"),
                         "contentUrl": a.get("contentUrl")} for a in task.get("attachments") or []],
        "submissions": [{"id": s.get("id"), "fileName": s.get("fileName"), "submitted": s.get("timestamp") or s.get("submittedDateTime"),
                         "contentUrl": s.get("contentUrl")} for s in student.get("submissions") or []],
        "teacherResponses": [{"id": r.get("id"), "fileName": r.get("fileName"), "uploaded": r.get("timestamp"),
                              "contentUrl": r.get("contentUri")} for r in student.get("teacherResponses") or []],
    }

