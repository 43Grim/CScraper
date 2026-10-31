"""Thin client for the Compass Education `/Services/*.svc` JSON API.

Every call reuses the browser session cookies captured by `auth.py`, so it acts
exactly like the Compass web page does. Responses wrap their payload in `d`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class CompassError(Exception):
    pass


class SessionExpired(CompassError):
    """The saved login no longer works; the user has to sign in again."""


@dataclass
class Session:
    host: str                  # e.g. "auburnhs-vic.compass.education"
    user_id: int               # Compass.organisationUserId
    cookies: list[dict]        # {"name", "value", "domain", "path"} dicts
    user_name: str | None = None

    def to_json(self) -> dict:
        return {"host": self.host, "user_id": self.user_id, "user_name": self.user_name, "cookies": self.cookies}

    @classmethod
    def from_json(cls, data: dict) -> "Session":
        return cls(host=data["host"], user_id=int(data["user_id"]), cookies=data["cookies"], user_name=data.get("user_name"))


class CompassClient:
    PAGE_SIZE = 100

    def __init__(self, session: Session, base_url: str | None = None, timeout: float = 60):
        self.session = session
        self.base_url = (base_url or f"https://{session.host}").rstrip("/")
        self.timeout = timeout
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
        })
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(502, 503, 504),
                      allowed_methods=frozenset({"GET", "POST"}), raise_on_status=False)
        self.http.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        self.http.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        for c in session.cookies:
            self.http.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))

    # ── low level ────────────────────────────────────────────────────
    def _url(self, service: str, method: str) -> str:
        return f"{self.base_url}/Services/{service}.svc/{method}"

    def _decode(self, resp: requests.Response) -> Any:
        ctype = resp.headers.get("content-type", "")
        if resp.status_code in (401, 403) or "login" in resp.url.lower() or "text/html" in ctype:
            raise SessionExpired(f"Compass returned {resp.status_code} ({ctype or 'no content type'}) for {resp.url}")
        if resp.status_code >= 400:
            raise CompassError(f"{resp.status_code} from {resp.url}: {resp.text[:300]}")
        data = resp.json()
        return data.get("d", data) if isinstance(data, dict) else data

    def post(self, service: str, method: str, body: dict | None = None) -> Any:
        resp = self.http.post(
            self._url(service, method),
            params={"sessionstate": "readonly", "_dc": int(time.time() * 1000)},
            json=body or {},
            timeout=self.timeout,
        )
        return self._decode(resp)

    def get_reference(self, method: str) -> Any:
        """ReferenceDataCache lookups are plain GETs."""
        resp = self.http.get(
            self._url("ReferenceDataCache", method),
            params={"sessionstate": "readonly", "page": 1, "start": 0, "limit": 1000, "_dc": int(time.time() * 1000)},
            timeout=self.timeout,
        )
        return self._decode(resp)

    def check(self) -> None:
        """Raises SessionExpired if the cookies no longer work.

        Reference data (e.g. academic groups) is served even when signed out, so this
        loads a page and checks Compass doesn't bounce it to the login page."""
        resp = self.http.get(self.base_url + "/", timeout=self.timeout)
        if "login" in resp.url.lower() or resp.status_code in (401, 403):
            raise SessionExpired("Compass sent the login page: this session is not signed in.")

    # ── data ─────────────────────────────────────────────────────────
    def academic_groups(self) -> list[dict]:
        return list(self.get_reference("GetAllAcademicGroups") or [])

    def grading_schemes(self) -> list[dict]:
        return list(self.get_reference("GetGradingSchemesForLearningTasks") or [])

    def task_categories(self) -> list[dict]:
        return list(self.post("LearningTasks", "GetAllTaskCategories") or [])

    def iter_learning_tasks(self, academic_group_id: int, include_hidden: bool = False) -> Iterator[tuple[dict, int]]:
        """Yields (task, total) for every task in one academic year, paging as needed.

        The web page only ever loads the first 20; this keeps going until `total`.
        """
        page, start, seen = 1, 0, 0
        while True:
            d = self.post("LearningTasks", "GetAllLearningTasksByUserId", {
                "academicGroupId": academic_group_id,
                "userId": self.session.user_id,
                "showHiddenTasks": include_hidden,
                "page": page,
                "start": start,
                "limit": self.PAGE_SIZE,
            })
            data = (d or {}).get("data") or []
            total = int((d or {}).get("total") or 0)
            for task in data:
                yield task, total
            seen += len(data)
            if not data or seen >= total:
                return
            page += 1
            start += self.PAGE_SIZE

    def rubrics_by_wiki_node_ids(self, wiki_node_ids: Iterable[int]) -> list[dict]:
        ids = sorted({int(i) for i in wiki_node_ids if i is not None})
        out: list[dict] = []
        for i in range(0, len(ids), 25):
            chunk = ids[i:i + 25]
            out.extend(self.post("Rubrics", "GetRubricsByWikiNodeIds",
                                 {"wikiNodeIds": chunk, "page": 1, "start": 0, "limit": 25}) or [])
        return out

    # ── files ────────────────────────────────────────────────────────
    def attachment_url(self, attachment_id: str, file_name: str) -> str:
        q = requests.compat.urlencode({"id": attachment_id, "originalFileName": file_name})
        return f"{self.base_url}/Services/FileAssets.svc/DownloadFile?{q}"

    def submission_url(self, task_id: int, submission_id: int) -> str:
        return f"{self.base_url}/Services/FileDownload/FileRequestHandler?FileDownloadType=2&taskId={task_id}&submissionId={submission_id}"

    def teacher_response_url(self, task_id: int, response_id: int) -> str:
        return f"{self.base_url}/Services/FileDownload/FileRequestHandler?FileDownloadType=4&taskId={task_id}&responseId={response_id}"

    def download(self, url: str, dest, chunk: int = 1 << 16) -> int:
        """Streams a file to `dest` (a Path). Returns the byte count."""
        with self.http.get(url, stream=True, timeout=self.timeout) as resp:
            ctype = resp.headers.get("content-type", "")
            if resp.status_code in (401, 403) or ("text/html" in ctype and "login" in resp.url.lower()):
                raise SessionExpired(f"Download redirected to login: {url}")
            if resp.status_code >= 400:
                raise CompassError(f"{resp.status_code} downloading {url}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            size = 0
            with open(tmp, "wb") as fh:
                for block in resp.iter_content(chunk):
                    fh.write(block)
                    size += len(block)
            tmp.replace(dest)
            return size
