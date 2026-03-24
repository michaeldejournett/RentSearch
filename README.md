# RentSearch

AI-powered apartment finder. Give it locations, commute constraints, and plain-English feature preferences — it searches the web, scores every listing with Claude AI, and exports a ranked Excel report.

---

## For end users — download the app

Pre-built executables are distributed via **GitHub Releases**:

| Platform | File |
|---|---|
| Windows | `RentSearch.exe` |
| Linux | `RentSearch` (binary) |

Just download and run — no installation required.

**You will need a Claude API key** (free to sign up): [console.anthropic.com](https://console.anthropic.com)
Enter it in the **Settings** screen on first launch.

---

## For developers — run from source

### Prerequisites
- Python 3.9+
- A Claude API key

### Setup
```bash
git clone https://github.com/yourusername/RentSearch
cd RentSearch
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### Run the desktop app
```bash
flet run main.py
```

### Run as a web app (mobile-accessible)
```bash
flet run --web --port 8080 main.py
# Open http://localhost:8080 on any device on your network
```

### Build a standalone executable
```bash
# Windows (run on Windows):
flet build windows --product-name "RentSearch" --product-version "1.0.0"

# Linux (run on Linux):
flet build linux --product-name "RentSearch" --product-version "1.0.0"
```

---

## How it works

1. **Add locations** — workplace, gym, family, etc. — with an importance weight (1–10)
2. **Set a max distance** — hard filter: listings beyond this are excluded
3. **Describe what you want** in plain English ("pet friendly", "in-unit laundry", "modern kitchen") with importance weights
4. **Click Find Apartments** — the app:
   - Searches DuckDuckGo for current listings in your area
   - Scrapes listing pages where possible
   - Uses Claude AI to extract structured data (address, price, beds, baths)
   - Uses Claude AI to score each listing against your criteria
   - Calculates straight-line distances to your important locations
5. **Download the Excel report** — fully ranked with scores, distances, and AI notes per criterion

---

## Configuration

All settings (including your API key) are stored in `~/.rentsearch/config.json` — never inside the project directory.

---

## Privacy

- Your Claude API key is stored locally only and never transmitted anywhere except the Anthropic API
- Apartment searches go through DuckDuckGo (no account required)
- No data is collected or shared by this app
