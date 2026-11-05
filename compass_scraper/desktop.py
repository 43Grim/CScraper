"""Adds the app to the system's app launcher: the Linux app menu, the Windows Start menu or the macOS Applications folder."""
from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "Compass Scraper"
_PLACES = {"linux": "app menu", "win32": "Start menu", "darwin": "Applications"}


def _system() -> str:
    return "linux" if sys.platform.startswith("linux") else sys.platform


def supported() -> bool:
    return _system() in _PLACES


def place() -> str:
    """What this system calls the place the app gets added to."""
    return _PLACES.get(_system(), "app menu")


def icon_path() -> Path:
    return Path(__file__).with_name("icon.svg")


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install() -> Path:
    """Adds the app for the current user and returns the launcher's path."""
    installers = {"linux": _install_linux, "win32": _install_windows, "darwin": _install_macos}
    if _system() not in installers:
        raise OSError(f"Adding {APP_NAME} to the app launcher isn't supported on {sys.platform}.")
    return installers[_system()]()


# ── Linux: a .desktop file and an SVG icon ──────────────────────────
def _install_linux() -> Path:
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    icon = data / "icons" / "hicolor" / "scalable" / "apps" / "compass-scraper.svg"
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icon_path(), icon)
    entry = data / "applications" / "compass-scraper.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    launch = f'Exec="{sys.executable}"\n' if _frozen() else f'Exec="{sys.executable}" -m compass_scraper.gui\nPath={Path.cwd()}\n'
    entry.write_text(
        f"[Desktop Entry]\nType=Application\nName={APP_NAME}\n"
        "Comment=Back up your Compass learning tasks, grades and feedback\n"
        f"{launch}Icon=compass-scraper\nTerminal=false\n"
        "Categories=Education;Office;\nStartupWMClass=compass-scraper\n"
    )
    entry.chmod(0o755)
    return entry


# ── Windows: a shortcut in the Start menu ───────────────────────────
_SHORTCUT = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CS_LINK); $s.TargetPath = $env:CS_TARGET; "
             "$s.Arguments = $env:CS_ARGS; $s.WorkingDirectory = $env:CS_DIR; $s.Description = $env:CS_NAME; $s.Save()")


def _install_windows() -> Path:
    programs = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True, exist_ok=True)
    link = programs / f"{APP_NAME}.lnk"
    exe = Path(sys.executable)
    if _frozen():
        target, args, folder = exe, "", exe.parent
    else:   # pythonw opens the app without a console window
        windowless = exe.with_name("pythonw.exe")
        target, args, folder = (windowless if windowless.exists() else exe), "-m compass_scraper.gui", Path.cwd()
    # The paths go through the environment so that spaces and quotes in them can't break the script.
    env = {**os.environ, "CS_LINK": str(link), "CS_TARGET": str(target), "CS_ARGS": args, "CS_DIR": str(folder), "CS_NAME": APP_NAME}
    _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _SHORTCUT], env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return link


# ── macOS: the app in the Applications folder ───────────────────────
def _running_bundle() -> Path | None:
    if not _frozen():
        return None
    return next((p for p in Path(sys.executable).resolve().parents if p.suffix == ".app"), None)


def _install_macos() -> Path:
    system_apps, my_apps = Path("/Applications"), Path.home() / "Applications"
    bundle = _running_bundle()
    if bundle and bundle.parent in (system_apps, my_apps):
        return bundle   # already there
    folder = system_apps if os.access(system_apps, os.W_OK) else my_apps
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{APP_NAME}.app"
    # Built in a temporary folder and swapped in at the end, so a failed copy leaves any existing app alone.
    tmp = folder / f".{APP_NAME}.app.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        if bundle:
            # A real copy, not a link: macOS may run a downloaded app from a temporary location. ditto keeps its signature.
            _run(["ditto", str(bundle), str(tmp)])
        else:
            _write_source_launcher(tmp)
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest


def _write_source_launcher(app: Path) -> None:
    """A small .app that starts the program from its source folder (when not running a packaged build)."""
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump({"CFBundleName": APP_NAME, "CFBundleExecutable": APP_NAME, "CFBundleIdentifier": "education.compass-scraper",
                       "CFBundlePackageType": "APPL"}, f)
    script = contents / "MacOS" / APP_NAME
    script.write_text(f"#!/bin/sh\ncd {shlex.quote(str(Path.cwd()))}\nexec {shlex.quote(sys.executable)} -m compass_scraper.gui\n")
    script.chmod(0o755)


def _run(cmd: list[str], **kwargs) -> None:
    """Runs a helper program, reporting any failure as an OSError."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300, **kwargs)
    except subprocess.CalledProcessError as e:
        raise OSError((e.stderr or e.stdout or str(e)).strip()) from e
    except subprocess.TimeoutExpired as e:
        raise OSError(f"{cmd[0]} took too long to finish.") from e
