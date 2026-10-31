"""Entry point for PyInstaller builds (it needs a plain script, not a package module)."""
import sys

from compass_scraper.gui import main

if __name__ == "__main__":
    sys.exit(main())
