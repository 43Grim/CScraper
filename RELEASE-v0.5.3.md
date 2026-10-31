## Compass Scraper 0.5.3

Timeline, performance graphs, task status and search everywhere.

### Download

| System | File |
|---|---|
| Windows 10/11 | `Compass-Scraper-0.5.3-Windows.zip`: unzip it, then run `Compass Scraper.exe` |
| macOS | `Compass-Scraper-0.5.3-macOS.zip`: unzip it, then right-click **Compass Scraper.app** and choose **Open** the first time (the app isn't signed) |
| Linux | `Compass-Scraper-0.5.3-Linux.tar.gz`: extract it and run `Compass Scraper/Compass Scraper` |

### New

- **Timeline:** every due date in one list (Overdue, Today, This week, Next week, Later).
  - Add your own items, mark things done, and remove tasks you don't need to see.
  - Export to Google, Apple or Outlook Calendar as an `.ics` file.
- **Performance:** graphs for each academic year. It only includes Assessments and Assignments.
  - Every marked task falls into exactly one category: **VCE Number Scores** (e.g. 9.5), **SACs** (percentages) or **Exams** (percentages on tasks with "exam" in the name).
  - Each category shows marks task by task (or by due date), your average per subject, and a results table coloured Towards, At, Above or Well above level.
  - A results breakdown counts every level result.
- **Task status:** Graded, Submitted, Done, Overdue, Due soon or Pending.
  - Tasks with a mark or an uploaded file count as complete automatically.
  - You can mark any other task done yourself.
- **Search everything (Ctrl+K):** search every task in every year.
  - Use filters like `status:overdue`, `has:rubric` or `subject:english`.
  - Browse also has Status and Score type filters.
- **HTML portfolio:** shows the same status badges and has the same status and "has" filters.
- **Overview:** now shows how many tasks are completed or overdue, and Coming up includes your own items.

### Fixes

- Bare numbers too big to be a level score (e.g. 100 or 82) now count as percentages, so they go to SACs or Exams, never VCE Number Scores.
- Average by subject now scrolls when you have lots of subjects, and scroll bars match the theme.
- Input boxes on the Sync page are now the same height.
- Dropdowns are redesigned to match the light and dark themes, and their hover text is readable in light mode.

### Known issues

- **Windows:** recent Chrome and Edge lock their cookies, so the app can't read your session from them. Use Firefox, or **Paste cookie instead…** in the sign-in window.
- Tasks without an online submission (for example, in-class tests) show as Overdue until a result comes out. Use **Mark done** for those.
