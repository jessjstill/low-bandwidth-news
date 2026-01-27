# 🗞️ Low-Bandwidth News Aggregator

A lightweight RSS feed aggregator that uses Claude AI to create curated daily briefings on crypto, policy, and tech research.

## Features

- 📡 **Multi-format support**: RSS, Atom (ArXiv), podcasts, and web scraping
- 🧠 **AI-powered summaries**: Claude analyzes and organizes content
- 📊 **15 curated sources**: Government, EU policy, crypto, and research feeds
- 🌐 **GitHub Pages ready**: Deploy as a static website
- ⚡ **Low bandwidth**: Fetches only metadata, not full content

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/low-bandwidth-news.git
cd low-bandwidth-news
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up your API key

```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
```

### 4. Run the aggregator

```bash
python src/main.py
```

Your briefing will be saved as `Daily_Briefing_YYYY-MM-DD.md`

## Project Structure

```
low-bandwidth-news/
├── .env                 # Your API key (not committed)
├── .env.example         # Template for .env
├── .gitignore
├── README.md
├── requirements.txt
├── data/
│   └── feeds.csv        # Feed sources configuration
├── src/
│   └── main.py          # Main aggregator script
└── docs/                # GitHub Pages (optional)
    ├── index.html
    └── latest.md
```

## Feed Sources

The aggregator monitors 15 sources across categories:

| Category | Sources |
|----------|---------|
| Research | ArXiv AI/Crypto |
| Crypto | Vitalik Buterin, The Block, Unchained |
| Tech | TechPolicy Press |
| US Gov | Federal Register, Congressional Bills, Congressional Record, GAO |
| EU Tech Policy | EU Parliament (Internal Market), European Commission (DG GROW) |
| EU Finance | EU Parliament (Economic Affairs), ECB |
| Macro | Forward Guidance, Bell Curve podcasts |

Edit `data/feeds.csv` to add or modify sources.

## Deploying to GitHub Pages

1. Go to repo **Settings** → **Pages**
2. Set source to `main` branch, `/docs` folder
3. Run `python src/main.py` to generate `docs/latest.md`
4. Commit and push

Your site will be live at: `https://YOUR_USERNAME.github.io/low-bandwidth-news/`

## Automation with GitHub Actions

Create `.github/workflows/daily-briefing.yml` to run automatically:

```yaml
name: Daily Briefing
on:
  schedule:
    - cron: '0 6 * * *'  # 6 AM UTC daily
  workflow_dispatch:

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python src/main.py
        env:
          CLAUDE_API_KEY: ${{ secrets.CLAUDE_API_KEY }}
      - run: |
          git config user.name "GitHub Actions"
          git config user.email "actions@github.com"
          git add .
          git commit -m "📰 Daily briefing" || exit 0
          git push
```

Add `CLAUDE_API_KEY` to repo **Settings** → **Secrets** → **Actions**.

## License

MIT

---

*Built with RSS feeds, Python, and Claude AI*
