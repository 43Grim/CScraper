## Compass Scraper 0.5.6

A new Reports page brings your school reports into the app.

### Download

| System | File |
|---|---|
| Windows 10/11 | `Compass-Scraper-0.5.6-Windows.zip`: unzip it, then run `Compass Scraper.exe` |
| macOS | `Compass-Scraper-0.5.6-macOS.zip`: unzip it and open **Compass Scraper.app**. The app isn't notarized by Apple, so macOS blocks it the first time: open **System Settings → Privacy & Security** and click **Open Anyway** |
| Linux | `Compass-Scraper-0.5.6-Linux.tar.gz`: extract it and run `Compass Scraper/Compass Scraper` |

### New

- **Reports page:** in Compass, open the **Reports** tab and use **Download All Semester Reports**, then import the ZIP into the app.
- **Only what matters is kept:** Victorian Curriculum levels for each strand, learning behaviours for each subject and term, and class attendance and teacher for each subject. Teacher comments and everything else are ignored.
- **Curriculum levels:** each level is coloured against the expected level. 7.0 is the start of Level 7 and 7.5 is halfway through it.
- **Graphs:** see your levels by learning area and your behaviours over time, plus attendance by subject.
- **Behaviour guide:** a button that shows the school's table of what each rating means.
- **No need to keep the ZIP:** the data is saved in your portfolio as `reports.json`, with the guide at `School Reports/learning-behaviour-guide.png`.

### Changes

- **Keyboard shortcuts:** **Ctrl+5** now opens Reports and **Ctrl+6** opens Sync.
- **New dependency:** the app now uses `pdfplumber` to read report PDFs. This only matters if you run from source.

### Known issues

- **Windows:** recent Chrome and Edge lock their cookies, so the app can't read your session from them. Use **Sign in here**, Firefox or Zen.
- **Windows:** the Start menu shortcut uses a generic icon for now.
- Tasks without an online submission (for example, in-class tests) show as Overdue until a result comes out. Use **Mark done** for those.
