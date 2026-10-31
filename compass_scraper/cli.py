"""Command line entry point:  python -m compass_scraper  (or the `compass-scraper` command)."""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress as RichProgress, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from . import __version__
from .auth import BROWSERS, forget_session, get_session, save_session, session_from_cookie_header
from .client import CompassClient, CompassError, SessionExpired
from .scrape import Cancelled, Progress, run

DEFAULT_HOST = "auburnhs-vic.compass.education"


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="compass-scraper", description="Download your Compass learning tasks, grades, feedback, rubrics and files into an HTML portfolio.")
    p.add_argument("--host", default=DEFAULT_HOST, help=f"your school's Compass address (default: {DEFAULT_HOST})")
    p.add_argument("--year", action="append", metavar="YEAR",
                   help="academic year to include, e.g. 2025 (repeatable). Default: every year")
    p.add_argument("--out", type=Path, help="output folder (default: ./compass-portfolio-<date>)")
    p.add_argument("--no-files", action="store_true", help="skip downloading attachments, submissions and teacher responses")
    p.add_argument("--no-zip", action="store_true", help="don't build the ZIP archive")
    p.add_argument("--include-hidden", action="store_true", help="also include tasks Compass marks as hidden")
    p.add_argument("--workers", type=int, default=4, help="parallel downloads (default 4)")
    p.add_argument("--browser", default="Auto", choices=["Auto", *BROWSERS],
                   help="browser you signed in to Compass with (default: try them all)")
    p.add_argument("--cookie", metavar="HEADER", help="use this Cookie header (copied from DevTools) instead of reading a browser")
    p.add_argument("--user-id", type=int, help="your Compass user ID, if it can't be detected")
    p.add_argument("--diagnose", action="store_true", help="print what the app can see in each browser (no cookie values) and exit")
    p.add_argument("--relogin", action="store_true", help="ignore the saved session and read a fresh one from the browser")
    p.add_argument("--logout", action="store_true", help="delete the saved session and exit")
    p.add_argument("--list-years", action="store_true", help="show the academic years Compass has and exit")
    p.add_argument("--install-desktop", action="store_true", help="add the desktop app to your application menu (Linux) and exit")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    console = Console()
    host = args.host.replace("https://", "").replace("http://", "").strip("/").split("/")[0]

    if args.install_desktop:
        from . import desktop
        console.print(f"Launcher written to {desktop.install()}")
        return 0

    if args.diagnose:
        from .auth import diagnose
        print(diagnose(host))
        return 0

    if args.logout:
        forget_session(host)
        console.print("Saved session deleted.")
        return 0

    log = lambda msg: console.print(f"[dim]{msg}[/dim]")
    try:
        if args.cookie:
            session = session_from_cookie_header(host, args.cookie, user_id=args.user_id)
            save_session(session)
        else:
            session = get_session(host, browser=args.browser, relogin=args.relogin, user_id=args.user_id, log=log)
    except Exception as e:
        console.print(f"[red]Sign-in failed:[/red] {e}")
        return 1
    console.print(f"Signed in as [bold]{session.user_name or session.user_id}[/bold] on {host}")
    client = CompassClient(session)

    if args.list_years:
        for g in client.academic_groups():
            console.print(f"  {g.get('importIdentifier') or '':>6}  {g.get('name')}  (id {g.get('id')})")
        return 0

    out = (args.out or Path(f"compass-portfolio-{datetime.now():%Y-%m-%d}")).resolve()
    started = time.time()

    with RichProgress(
        TextColumn("[bold cyan]{task.description}"), BarColumn(), MofNCompleteColumn(),
        TimeElapsedColumn(), TextColumn("ETA"), TimeRemainingColumn(), console=console, transient=False,
    ) as bar:
        phase = bar.add_task("Starting", total=None)
        files = bar.add_task("Files", total=None, visible=False)
        fails: list[str] = []

        def file_done(name, ok, err):
            bar.advance(files)
            if not ok:
                fails.append(name)
                bar.console.print(f"[red]  ✗ {name}: {err}[/red]")

        prog = Progress(
            phase=lambda msg: bar.update(phase, description=msg),
            files_total=lambda n: bar.update(files, total=n, visible=n > 0),
            file_done=file_done,
            log=lambda msg: bar.console.print(f"  {msg}"),
        )
        try:
            res = run(client, out, years=args.year, progress=prog, download=not args.no_files,
                      zip_output=not args.no_zip, include_hidden=args.include_hidden, workers=args.workers)
        except SessionExpired:
            console.print("[red]Your Compass session expired part-way through.[/red] Sign in to Compass in your browser and run again with --relogin; files already downloaded are kept.")
            return 2
        except CompassError as e:
            console.print(f"[red]Compass error:[/red] {e}")
            return 1
        bar.update(phase, total=1, completed=1)

    graded = sum(1 for t in res.tasks if any(g["display"] for g in t["grades"]))
    console.print()
    console.print(f"[green]Done[/green] in {time.time() - started:.0f}s: {len(res.tasks)} tasks ({graded} with results), "
                  f"{sum(len(t['rubrics']) for t in res.tasks)} rubrics, {res.files_ok} files downloaded"
                  + (f", {res.files_skipped} already there" if res.files_skipped else "")
                  + (f", [red]{len(res.files_failed)} failed[/red]" if res.files_failed else ""))
    console.print(f"Portfolio: [bold]{out / 'index.html'}[/bold]")
    if res.zip_path:
        console.print(f"ZIP:       [bold]{res.zip_path}[/bold]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
