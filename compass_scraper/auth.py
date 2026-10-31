"""Signing in to Compass.

You sign in to Compass yourself, in your normal browser. The app then reads the
Compass session cookies from that browser's cookie store (the same way tools
like yt-dlp do), works out your Compass user ID from the page, and saves the
session so later runs reuse it until it expires.

If reading the browser doesn't work, a cookie header copied from DevTools can be
pasted instead (see `session_from_cookie_header`).
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

import requests

from .client import USER_AGENT, CompassClient, CompassError, Session, SessionExpired

# Display name -> browser_cookie3 loader name, in the order "Auto" tries them.
BROWSERS = {
    "Firefox": "firefox",
    "Zen": "firefox",          # Firefox-based, same cookie format
    "Safari": "safari",
    "Chrome": "chrome",
    "Arc": "arc",
    "Chromium": "chromium",
    "Brave": "brave",
    "Edge": "edge",
    "Vivaldi": "vivaldi",
    "Opera": "opera",
    "LibreWolf": "librewolf",
}


# ── saved session ────────────────────────────────────────────────────
def session_path(host: str) -> Path:
    base = Path(os.environ.get("COMPASS_SCRAPER_HOME", Path.home() / ".compass-scraper"))
    return base / f"session-{host}.json"


def load_session(host: str) -> Session | None:
    p = session_path(host)
    if not p.exists():
        return None
    try:
        return Session.from_json(json.loads(p.read_text()))
    except (ValueError, KeyError):
        return None


def save_session(session: Session) -> Path:
    p = session_path(session.host)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(session.to_json(), indent=1))
    try:
        p.chmod(0o600)  # contains login cookies
    except OSError:
        pass
    return p


def forget_session(host: str) -> None:
    session_path(host).unlink(missing_ok=True)


# ── reading cookies ──────────────────────────────────────────────────
def _for_host(host: str, cookies: list[dict]) -> list[dict]:
    return [c for c in cookies if host.endswith((c.get("domain") or host).lstrip("."))]


MAC = sys.platform == "darwin"
WINDOWS = sys.platform.startswith("win")
_MAC_SUPPORT = "~/Library/Application Support"

# Linux config folders of Chromium-based browsers. Every profile in every matching
# folder is tried, which also covers variants such as Brave Beta / Nightly / Origin.
_LINUX_DIRS = {
    "Chrome": ["~/.config/google-chrome*", "~/.var/app/com.google.Chrome/config/google-chrome*"],
    "Chromium": ["~/.config/chromium", "~/.var/app/org.chromium.Chromium/config/chromium", "~/snap/chromium/common/chromium"],
    "Brave": ["~/.config/BraveSoftware/*", "~/.var/app/com.brave.Browser/config/BraveSoftware/*"],
    "Edge": ["~/.config/microsoft-edge*"],
    "Vivaldi": ["~/.config/vivaldi*"],
    "Opera": ["~/.config/opera*"],
}


# Firefox-family profile folders (newer Firefox on Linux uses ~/.config/mozilla).
_FIREFOX_DIRS = {
    "Firefox": ["~/.mozilla/firefox", "~/.config/mozilla/firefox", "~/snap/firefox/common/.mozilla/firefox",
                "~/.var/app/org.mozilla.firefox/.mozilla/firefox", "~/.var/app/org.mozilla.firefox/config/mozilla/firefox"],
    "LibreWolf": ["~/.librewolf", "~/.config/librewolf/librewolf", "~/.var/app/io.gitlab.librewolf-community/.librewolf"],
}


_FIREFOX_DIRS["Zen"] = ["~/.zen", "~/.var/app/app.zen_browser.zen/.zen", "~/.config/zen"]

# macOS: Firefox-family profiles live in .../Profiles, Chromium-family in per-browser folders.
_MAC_FIREFOX_DIRS = {
    "Firefox": [f"{_MAC_SUPPORT}/Firefox/Profiles"],
    "Zen": [f"{_MAC_SUPPORT}/zen/Profiles"],
    "LibreWolf": [f"{_MAC_SUPPORT}/librewolf/Profiles"],
}
_MAC_DIRS = {
    "Chrome": [f"{_MAC_SUPPORT}/Google/Chrome*"],
    "Arc": [f"{_MAC_SUPPORT}/Arc/User Data"],
    "Chromium": [f"{_MAC_SUPPORT}/Chromium"],
    "Brave": [f"{_MAC_SUPPORT}/BraveSoftware/Brave-Browser*"],
    "Edge": [f"{_MAC_SUPPORT}/Microsoft Edge*"],
    "Vivaldi": [f"{_MAC_SUPPORT}/Vivaldi"],
    "Opera": [f"{_MAC_SUPPORT}/com.operasoftware.Opera*"],
}
_WIN_FIREFOX_DIRS = {
    "Firefox": [r"%APPDATA%\Mozilla\Firefox\Profiles"],
    "Zen": [r"%APPDATA%\zen\Profiles"],
    "LibreWolf": [r"%APPDATA%\librewolf\Profiles"],
}
SAFARI_FILES = ["~/Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies",
                "~/Library/Cookies/Cookies.binarycookies"]


def supported_browsers() -> list[str]:
    """Browsers worth offering on this computer."""
    return [b for b in BROWSERS if b != "Safari" or MAC]


def _profile_cookie_files(browser: str) -> list[Path]:
    files = set()
    if browser == "Safari":
        return [Path(os.path.expanduser(f)) for f in SAFARI_FILES if os.path.exists(os.path.expanduser(f))][:1] if MAC else []
    if MAC or WINDOWS:
        fx = _MAC_FIREFOX_DIRS if MAC else _WIN_FIREFOX_DIRS
        for pattern in fx.get(browser, []):
            root = os.path.expandvars(os.path.expanduser(pattern))
            files.update(Path(f) for f in glob.glob(os.path.join(glob.escape(root), "*", "cookies.sqlite")))
        if MAC:
            for pattern in _MAC_DIRS.get(browser, []):
                for root in glob.glob(os.path.expanduser(pattern)):
                    for rel in ("Default/Cookies", "Profile */Cookies", "Cookies"):
                        files.update(Path(f) for f in glob.glob(os.path.join(glob.escape(root), rel)))
        return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)
    if not sys.platform.startswith("linux"):
        return []
    for pattern in _FIREFOX_DIRS.get(browser, []):
        files.update(Path(f) for f in glob.glob(os.path.join(os.path.expanduser(pattern), "*", "cookies.sqlite")))
    for pattern in _LINUX_DIRS.get(browser, []):
        for root in glob.glob(os.path.expanduser(pattern)):
            for rel in ("Default/Cookies", "Default/Network/Cookies", "Profile */Cookies", "Profile */Network/Cookies", "Cookies"):
                files.update(Path(f) for f in glob.glob(os.path.join(root, rel)))
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)  # most recently used first


def _profile_label(f: Path) -> str:
    prof = f.parent.parent if f.parent.name == "Network" else f.parent
    return f"{prof.parent.name}/{prof.name}"


def cookies_from_browser(host: str, browser: str) -> list[tuple[str, list[dict]]]:
    """Compass cookies from one browser, as (where, cookies) for each profile that has any.
    `browser` is a key of BROWSERS."""
    import browser_cookie3

    loader = getattr(browser_cookie3, BROWSERS[browser])
    to_dicts = lambda jar: _for_host(host, [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path or "/"} for c in jar])
    found, errors = [], []
    for f in _profile_cookie_files(browser):
        try:
            cookies = to_dicts(loader(cookie_file=str(f), domain_name="compass.education"))
        except PermissionError:
            errors.append(_permission_hint(browser))
            continue
        except Exception as e:
            errors.append(f"{f}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
            continue
        if cookies:
            found.append((f"{browser} ({_profile_label(f)})", cookies))
    if not found and not _profile_cookie_files(browser) and browser not in ("Zen", "Safari"):
        cookies = to_dicts(loader(domain_name="compass.education"))  # library's default locations (Windows / macOS / Firefox)
        if cookies:
            found.append((browser, cookies))
    if not found and errors:
        raise CompassError("; ".join(errors[:3]))
    return found


def _permission_hint(browser: str) -> str:
    if MAC:
        return (f"macOS blocked access to {browser}'s cookies. Open System Settings → Privacy & Security → "
                "Full Disk Access, turn it on for Compass Scraper (or Terminal, if you run it from there), then try again. "
                "Or use “Sign in here” instead.")
    return f"Permission denied reading {browser}'s cookies."


def chromium_hint(browser: str) -> str:
    """Why a Chromium browser's cookies might be unreadable even though they were found."""
    if MAC:
        return (f"If macOS asked whether Compass Scraper may use “{browser} Safe Storage”, click Always Allow. "
                "If you clicked Deny, try again, or use Firefox, Zen, Safari or “Sign in here”.")
    if WINDOWS:
        return f"New versions of {browser} on Windows lock their cookies. Use Firefox, Zen or “Sign in here” instead."
    return ""


def parse_cookie_header(host: str, text: str) -> list[dict]:
    """Accepts `name=value; name2=value2` (a Cookie header copied from DevTools)."""
    text = text.strip()
    if text.lower().startswith("cookie:"):
        text = text[7:]
    out = []
    for part in text.split(";"):
        if "=" in part:
            name, value = part.split("=", 1)
            if name.strip():
                out.append({"name": name.strip(), "value": value.strip(), "domain": host, "path": "/"})
    return out


# ── who is signed in ─────────────────────────────────────────────────
_ID = re.compile(r"organisationUserId[\"']?\s*[:=]\s*[\"']?(\d+)")
_NAME = re.compile(r"organisationUserFirstAndLastname[\"']?\s*[:=]\s*[\"']([^\"'\\]{1,80})")


def identify(host: str, cookies: list[dict], base_url: str | None = None) -> tuple[int, str | None]:
    """Reads your Compass user ID and name from the page Compass serves when you're signed in."""
    base = (base_url or f"https://{host}").rstrip("/")
    http = requests.Session()
    http.headers["User-Agent"] = USER_AGENT
    for c in cookies:
        http.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
    for path in ("/", "/Records/UserNew.aspx"):
        resp = http.get(base + path, timeout=30)
        if "login" in resp.url.lower():
            raise SessionExpired("Compass sent the login page, so this browser isn't signed in to Compass.")
        m = _ID.search(resp.text)
        if m:
            name = _NAME.search(resp.text)
            return int(m.group(1)), (name.group(1) if name else None)
    raise CompassError("Signed in, but couldn't find your Compass user ID on the page. Enter it manually.")


def make_session(host: str, cookies: list[dict], user_id: int | None = None, base_url: str | None = None) -> Session:
    if not cookies:
        raise SessionExpired("No Compass cookies found.")
    name = None
    if user_id is None:
        user_id, name = identify(host, cookies, base_url=base_url)
    session = Session(host=host, user_id=int(user_id), user_name=name, cookies=cookies)
    CompassClient(session, base_url=base_url).check()
    return session


def session_from_browser(host: str, browser: str = "Auto", user_id: int | None = None, log=print) -> Session:
    """Finds a signed-in Compass session in the chosen browser (or any, for "Auto")."""
    names = supported_browsers() if browser == "Auto" else [browser]
    problems = []
    try:
        import browser_cookie3  # noqa: F401
    except ImportError:
        raise CompassError("The browser_cookie3 package isn't installed. Run:  uv add browser-cookie3   (or pip install browser-cookie3)")
    for b in names:
        try:
            sources = cookies_from_browser(host, b)
        except Exception as e:  # browser not installed, profile locked, keyring refused, ...
            problems.append(f"{b}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
            continue
        if not sources:
            problems.append(f"{b}: no Compass cookies")
            continue
        for where, cookies in sources:
            try:
                session = make_session(host, cookies, user_id=user_id)
                log(f"Found a signed-in Compass session in {where}.")
                return session
            except CompassError as e:
                hint = chromium_hint(b) if b not in ("Firefox", "Zen", "LibreWolf", "Safari") else ""
                problems.append(f"{where}: {e} {hint}".strip())
    raise SessionExpired(
        "Couldn't find a signed-in Compass session. Sign in to Compass in your browser first.\n  " + "\n  ".join(problems)
    )


def session_from_cookie_header(host: str, header: str, user_id: int | None = None) -> Session:
    return make_session(host, parse_cookie_header(host, header), user_id=user_id)


def get_session(host: str, browser: str = "Auto", relogin: bool = False, user_id: int | None = None, log=print) -> Session:
    """Returns a working session: the saved one if it still works, otherwise one read from the browser."""
    if not relogin:
        saved = load_session(host)
        if saved:
            try:
                CompassClient(saved).check()
                log("Using saved Compass session.")
                return saved
            except CompassError:
                log("Saved session has expired; reading a fresh one from your browser.")
    session = session_from_browser(host, browser=browser, user_id=user_id, log=log)
    save_session(session)
    return session


def diagnose(host: str) -> str:
    """A report of what the app can see, safe to share: cookie names only, never values."""
    import platform
    lines = [f"Compass Scraper diagnose for {host}", f"Python {sys.version.split()[0]} on {platform.platform()}"]
    try:
        import browser_cookie3
        lines.append(f"browser_cookie3 {getattr(browser_cookie3, '__version__', '?')}")
    except ImportError:
        lines.append("browser_cookie3 NOT INSTALLED  ->  uv add browser-cookie3")
        return "\n".join(lines)
    lines.append(f"DBUS_SESSION_BUS_ADDRESS {'set' if os.environ.get('DBUS_SESSION_BUS_ADDRESS') else 'NOT set'}")
    for b in supported_browsers():
        fn = BROWSERS[b]
        files = _profile_cookie_files(b)
        lines.append(f"\n[{b}] {len(files)} profile cookie file(s)")
        targets = [(str(f), {"cookie_file": str(f)}) for f in files] or ([] if b in ("Zen", "Safari") else [("library default location", {})])
        for label, kw in targets:
            try:
                jar = getattr(browser_cookie3, fn)(domain_name="compass.education", **kw)
                cookies = [c for c in jar]
            except PermissionError:
                lines.append(f"  {label}: BLOCKED by macOS privacy settings (needs Full Disk Access)")
                continue
            except Exception as e:
                lines.append(f"  {label}: ERROR {type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}")
                continue
            mine = _for_host(host, [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in cookies])
            names = ", ".join(f"{c.name}@{c.domain}{'' if c.expires else ' (session)'}{' EMPTY' if not c.value else ''}" for c in cookies) or "none"
            lines.append(f"  {label}: {len(cookies)} compass cookie(s): {names}")
            if not mine:
                continue
            http = requests.Session()
            http.headers["User-Agent"] = USER_AGENT
            for c in mine:
                http.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path") or "/")
            for path in ("/", "/Records/UserNew.aspx"):
                try:
                    r = http.get(f"https://{host}{path}", timeout=30)
                    lines.append(f"    GET {path} -> {r.status_code}, ended at {requests.utils.urlparse(r.url).path}, "
                                 f"{len(r.text)} chars, user id {'FOUND' if _ID.search(r.text) else 'not found'}")
                except Exception as e:
                    lines.append(f"    GET {path} -> ERROR {e}")
            try:
                r = http.get(f"https://{host}/Services/ReferenceDataCache.svc/GetAllAcademicGroups",
                             params={"sessionstate": "readonly", "page": 1, "start": 0, "limit": 1000},
                             headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
                lines.append(f"    API test -> {r.status_code} {r.headers.get('content-type', '')[:40]}, ended at {requests.utils.urlparse(r.url).path}")
            except Exception as e:
                lines.append(f"    API test -> ERROR {e}")
    return "\n".join(lines)
