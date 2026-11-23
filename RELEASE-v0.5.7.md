## Compass Scraper 0.5.7

Tasks with several VCE number scores are now marked fairly.

### Download

| System | File |
|---|---|
| Windows 10/11 | `Compass-Scraper-0.5.7-Windows.zip`: unzip it, then run `Compass Scraper.exe` |
| macOS | `Compass-Scraper-0.5.7-macOS.zip`: unzip it and open **Compass Scraper.app**. The app isn't notarized by Apple, so macOS blocks it the first time: open **System Settings → Privacy & Security** and click **Open Anyway** |
| Linux | `Compass-Scraper-0.5.7-Linux.tar.gz`: extract it and run `Compass Scraper/Compass Scraper` |

### Changes

- **Several number scores on one task:** some Year 10 and below tasks give a VCE number score for each curriculum strand. The app used to take only the first one. Now:
  - If the teacher's main result is a number score, that overall mark is used.
  - Otherwise every number score counts equally and the task's mark is their average (for example, Algebra 9.0 and Measurement 8.5 make 8.75).
  - Hover over the task on the Performance graph or table to see each score that went into the average.

### Known issues

- **Windows:** recent Chrome and Edge lock their cookies, so the app can't read your session from them. Use **Sign in here**, Firefox or Zen.
- **Windows:** the Start menu shortcut uses a generic icon for now.
- Tasks without an online submission (for example, in-class tests) show as Overdue until a result comes out. Use **Mark done** for those.
