## 📚 Compass Multi-Subject Assessment Scraper v0.5.0

A powerful, automated JavaScript console script designed to scrape assessment data, grades, teacher feedback, rubrics, and file attachments across multiple subjects from **Compass Education**, packaging everything into a clean HTML portfolio dashboard and a downloadable ZIP archive.
## Known Bugs
When ran the code sometimes does not block the downloads prompts when calling for downloading, please cancel any downloads apart from the final .zip that get's queued at the end of the script!

---

## ✨ Features

- **Multi-Subject**: Automatically traverses and structures learning tasks across all expanded subjects.
- **Deep Content Extraction**:
  - **Grades & Results**: Extracts numerical or letter grades and status details.
  - **Teacher Feedback**: Captures comments and feedback notes.
  ~~- **File Attachments & Submissions**: Uses `window.open` interception and direct asset link resolution to harvest student submissions, task attachments, and teacher response files.~~
- **Live Visual Dashboard**: Displays a sleek, non-intrusive floating overlay panel in the top-right corner with real-time progress counters, status phases, time elapsed, and dynamic ETAs.

---

## 🚀 How to Use

1. Navigate to **Compass** $\rightarrow$ **Learning Tasks** (ensure you are on the **All Subjects** view).
2. **Expand** your subject groups so the task list is fully visible.
3. Apply the **"Assessment"** category filter and at the bottom of the page set items from 20 to 500.
4. Open your browser's Developer Tools (**F12** or right-click $\rightarrow$ *Inspect*) and go to the **Console** tab.
5. Paste the entire contents of `CScraper` into the console and press **Enter**.
6. Let the script run unattended while tracking progress on the live dashboard.
7. On completion, two files will automatically download to your computer:

---

## ❗ Notice
Parts of this code repository were generated using artificial intelligence tools. Some scripts, functions, or documentation were created or assisted by AI models. 
This program is incredibly experimental and  is designed for personal academic record-keeping and portfolio generation on Compass Education portals. Use responsibly and in accordance with your educational institution's guidelines and terms of service.
