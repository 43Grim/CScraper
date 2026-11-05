## Compass Scraper 0.5.5

New CATs and SACs views, safer syncs and an app menu button on every system.

### Download

| System | File |
|---|---|
| Windows 10/11 | `Compass-Scraper-0.5.5-Windows.zip`: unzip it, then run `Compass Scraper.exe` |
| macOS | `Compass-Scraper-0.5.5-macOS.zip`: unzip it and open **Compass Scraper.app**. The app isn't notarized by Apple, so macOS blocks it the first time: open **System Settings → Privacy & Security** and click **Open Anyway** |
| Linux | `Compass-Scraper-0.5.5-Linux.tar.gz`: extract it and run `Compass Scraper/Compass Scraper` |

### New

- **CATs (Year 10 and below):** every marked assessment now sits under CATs, with a switch between **VCE Number Scores** and **Percentages**. The year level comes from the class code, such as `10MATEA`.
- **SACs (Year 11 and above):** switch between **Percentage** and **Performance**. Performance results such as High or High - Excellent are graphed as named bands, not made-up numbers.
- **Exams:** any marked task with the word "exam" in its name goes under Exams, in every year.
- **Add to app menu on every system:** add the app to the Windows Start menu or the macOS Applications folder. Linux keeps its app menu button.
- **Crash-safe sync:** your portfolio only changes once a sync has finished. If the app closes part-way, your files stay exactly as they were, and the next sync picks up what was already downloaded.
- **Academic years only:** HeadStart years are no longer synced or shown. Folders already downloaded for them stay on your computer until you delete them.

### Fixes

- The grade shown for a Year 10 task now puts a number score ahead of a percentage.
- A number under a row called Performance now counts as a percentage, and rows with a curriculum code (such as `VCM2MA`) count as number scores.
- Performance page cards no longer keep old labels when a year has no marks.
- The Results breakdown scrolls instead of cutting off rows.
- The Linux app menu entry now starts packaged builds correctly and uses the real app icon.
- The packaged app now includes its icon.

### Known issues

- **Windows:** recent Chrome and Edge lock their cookies, so the app can't read your session from them. Use **Sign in here**, Firefox or Zen.
- **Windows:** the Start menu shortcut uses a generic icon for now.
- Tasks without an online submission (for example, in-class tests) show as Overdue until a result comes out. Use **Mark done** for those.
