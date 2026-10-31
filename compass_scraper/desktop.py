"""Adds the app to the Linux application menu (a .desktop file plus an SVG icon)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="4" y="4" width="56" height="56" rx="14" fill="#2563eb"/>
<circle cx="32" cy="32" r="17" fill="none" stroke="#fff" stroke-width="4"/>
<path d="M32 19 L37 32 L32 45 L27 32 Z" fill="#fff"/>
<circle cx="32" cy="32" r="3" fill="#2563eb"/>
</svg>
"""


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def supported() -> bool:
    return sys.platform.startswith("linux")


def icon_path() -> Path:
    """The packaged icon, written next to the module on first use."""
    p = Path(__file__).with_name("icon.svg")
    if not p.exists():
        try:
            p.write_text(ICON)
        except OSError:
            pass
    return p


def install() -> Path:
    """Writes the launcher and icon for the current user and returns the .desktop path."""
    data = _data_home()
    icon = data / "icons" / "hicolor" / "scalable" / "apps" / "compass-scraper.svg"
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_text(ICON)
    entry = data / "applications" / "compass-scraper.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=Compass Scraper\n"
        "Comment=Back up your Compass learning tasks, grades and feedback\n"
        f'Exec="{sys.executable}" -m compass_scraper.gui\n'
        f"Path={Path.cwd()}\nIcon=compass-scraper\nTerminal=false\n"
        "Categories=Education;Office;\nStartupWMClass=compass-scraper\n"
    )
    entry.chmod(0o755)
    return entry


def uninstall() -> None:
    data = _data_home()
    for p in (data / "applications" / "compass-scraper.desktop", data / "icons" / "hicolor" / "scalable" / "apps" / "compass-scraper.svg"):
        p.unlink(missing_ok=True)
