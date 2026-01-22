"""
Low-Bandwidth News Aggregator
Fetches RSS/Atom feeds and podcast feeds, then uses Claude to create a daily briefing.
Outputs a Markdown table with one row per article.
"""

import os
import sys
import re
import time
import pandas as pd
import feedparser
import anthropic
import trafilatura
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Timezones
UTC = ZoneInfo("UTC")
EST = ZoneInfo("America/New_York")

# Load environment variables
load_dotenv()
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

if not CLAUDE_API_KEY:
    print("Error: CLAUDE_API_KEY not found.")
    print("   Please create a .env file in the project root with:")
    print("   CLAUDE_API_KEY=sk-ant-api03-YOUR_KEY_HERE")
    sys.exit(1)

client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)


def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('\n', ' ').replace('\r', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def parse_pub_date(entry) -> datetime | None:
    """Extract publication date from a feed entry and return as UTC-aware datetime."""
    # Try different date fields
    for field in ['published_parsed', 'updated_parsed', 'created_parsed']:
        parsed = getattr(entry, field, None)
        if parsed:
            try:
                # feedparser returns time structs in UTC, create UTC-aware datetime
                return datetime(*parsed[:6], tzinfo=UTC)
            except:
                pass
    return None


def is_today(pub_date: datetime | None) -> bool:
    """Check if a publication date is from today (UTC midnight-to-midnight)."""
    if not pub_date:
        return False
    today_utc = datetime.now(UTC).date()
    # Ensure we're comparing in UTC
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=UTC)
    return pub_date.astimezone(UTC).date() == today_utc


def format_pub_date(pub_date: datetime | None) -> str:
    """Format publication date as MM-DD-YYYY / HH:MM EST."""
    if not pub_date:
        return "N/A"
    # Convert to EST for display
    try:
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=UTC)
        pub_est = pub_date.astimezone(EST)
        return pub_est.strftime("%m-%d-%Y / %H:%M EST")
    except:
        return pub_date.strftime("%m-%d-%Y / %H:%M")


def fetch_rss(url: str, category: str, source_name: str, max_items: int = 20) -> list:
    """Fetch standard RSS/Atom feeds. Returns list of article dicts from today only."""
    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            return []

        articles = []
        for entry in feed.entries[:max_items]:
            pub_date = parse_pub_date(entry)
            if not is_today(pub_date):
                continue

            title = getattr(entry, 'title', 'No Title')
            link = getattr(entry, 'link', url)
            summary = clean_html(getattr(entry, 'summary', ''))[:500]

            articles.append({
                'category': category,
                'source': source_name,
                'title': title,
                'link': link,
                'raw_content': summary,
                'pub_date': pub_date
            })

        return articles
    except Exception as e:
        print(f"   Warning: {str(e)}")
        return []


def fetch_atom(url: str, category: str, source_name: str, max_items: int = 20) -> list:
    """Fetch Atom feeds (like ArXiv API). Returns list of article dicts from today only."""
    try:
        feed = feedparser.parse(url)
        articles = []

        for entry in feed.entries[:max_items]:
            pub_date = parse_pub_date(entry)
            if not is_today(pub_date):
                continue

            title = getattr(entry, 'title', 'No Title')
            link = getattr(entry, 'link', '')
            authors = ', '.join([a.get('name', '') for a in getattr(entry, 'authors', [])])
            summary = clean_html(getattr(entry, 'summary', ''))[:500]

            # Include authors in raw content for context
            raw = f"Authors: {authors}. {summary}" if authors else summary

            articles.append({
                'category': category,
                'source': source_name,
                'title': title,
                'link': link,
                'raw_content': raw,
                'pub_date': pub_date
            })

        return articles
    except Exception as e:
        print(f"   Warning: {str(e)}")
        return []


def fetch_podcast(url: str, category: str, source_name: str, max_items: int = 20) -> list:
    """Fetch podcast RSS feeds. Returns list of episode dicts from today only."""
    try:
        feed = feedparser.parse(url)
        articles = []

        for entry in feed.entries[:max_items]:
            pub_date = parse_pub_date(entry)
            if not is_today(pub_date):
                continue

            title = getattr(entry, 'title', 'No Title')
            link = getattr(entry, 'link', '')
            description = clean_html(getattr(entry, 'summary', getattr(entry, 'description', '')))[:500]

            articles.append({
                'category': category,
                'source': source_name,
                'title': title,
                'link': link,
                'raw_content': description,
                'pub_date': pub_date
            })

        return articles
    except Exception as e:
        print(f"   Warning: {str(e)}")
        return []


def fetch_scrape(url: str, category: str, source_name: str) -> list:
    """Scrape content from a webpage. Returns list with one article dict."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_links=False)
            if text:
                return [{
                    'category': category,
                    'source': source_name,
                    'title': f"{source_name} - Latest",
                    'link': url,
                    'raw_content': text[:800],
                    'pub_date': datetime.now(UTC)  # Assume scraped content is current
                }]
        return []
    except Exception as e:
        print(f"   Warning: {str(e)}")
        return []


def fetch_content(url: str, feed_type: str, category: str, source_name: str) -> list:
    """Route to appropriate fetcher based on feed type."""
    feed_type = (feed_type or 'rss').lower().strip()
    
    if feed_type == 'atom':
        return fetch_atom(url, category, source_name)
    elif feed_type == 'podcast':
        return fetch_podcast(url, category, source_name)
    elif feed_type == 'scrape':
        return fetch_scrape(url, category, source_name)
    else:
        return fetch_rss(url, category, source_name)


def generate_summaries(articles: list) -> list:
    """Send articles to Claude for summarization."""
    if not articles:
        return []
    
    # Build prompt with all articles
    articles_text = ""
    for i, article in enumerate(articles):
        articles_text += f"""
ARTICLE {i+1}:
Title: {article['title']}
Source: {article['source']}
Content: {article['raw_content']}
---
"""
    
    prompt = f"""You are a news analyst. For each article below, write a 1-2 sentence summary (max 30 words) capturing the key point.

Respond ONLY with a numbered list matching the article numbers. No other text.

Format:
1. [summary for article 1]
2. [summary for article 2]
...

ARTICLES:
{articles_text}
"""
    
    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=4000,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )
        
        response_text = message.content[0].text
        
        # Parse numbered summaries
        summaries = {}
        for line in response_text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            # Match "1. summary" or "1) summary" or just "1 summary"
            match = re.match(r'^(\d+)[\.\)\s]+(.+)$', line)
            if match:
                num = int(match.group(1))
                summary = match.group(2).strip()
                summaries[num] = summary
        
        # Assign summaries to articles
        for i, article in enumerate(articles):
            article['summary'] = summaries.get(i + 1, "Summary unavailable")
        
        return articles
        
    except anthropic.APIError as e:
        print(f"Claude API Error: {e}")
        for article in articles:
            article['summary'] = "Error generating summary"
        return articles


def escape_markdown(text: str) -> str:
    """Escape pipe characters for Markdown tables."""
    return text.replace('|', '\\|')


def main():
    print("Starting News Aggregator...")
    print(f"Date: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")
    print("-" * 50)

    # Locate CSV file relative to script
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(base_dir, 'data', 'feeds.csv')

    if not os.path.exists(csv_path):
        print(f"Error: Could not find {csv_path}")
        print("   Make sure feeds.csv is in the 'data' folder.")
        return

    # Read feeds
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} feed sources\n")

    # Fetch all articles
    all_articles = []

    for index, row in df.iterrows():
        source_name = row['Source Name']
        category = row['Category']
        url = row['URL']
        feed_type = row.get('Type', 'rss')
        
        if pd.isna(feed_type) or feed_type == '':
            feed_type = 'rss'
        
        print(f"Fetching: {source_name} ({feed_type})...")
        
        articles = fetch_content(url, feed_type, category, source_name)
        print(f"   Found {len(articles)} items")
        all_articles.extend(articles)

    print(f"\nTotal articles fetched: {len(all_articles)}")
    print("-" * 50)

    if not all_articles:
        print("No articles found. Check your feed URLs.")
        return

    # Generate summaries with Claude
    print("Generating summaries with Claude...")
    print("   (This may take a moment...)")
    
    # Process in batches of 20 to avoid token limits
    batch_size = 20
    for i in range(0, len(all_articles), batch_size):
        batch = all_articles[i:i + batch_size]
        print(f"   Processing articles {i+1}-{min(i+batch_size, len(all_articles))}...")
        generate_summaries(batch)

    # Build Markdown table
    print("\nBuilding Markdown table...")
    
    # Sort by publication date (newest first), then by category
    all_articles.sort(key=lambda x: (x.get('pub_date') or datetime.min), reverse=True)
    
    # Create table
    table_lines = [
        "| Date/Time | Category | Source | Title | Summary | Link |",
        "|-----------|----------|--------|-------|---------|------|"
    ]

    for article in all_articles:
        pub_date_str = format_pub_date(article.get('pub_date'))
        category = escape_markdown(article['category'])
        source = escape_markdown(article['source'])
        title = escape_markdown(article['title'][:60] + '...' if len(article['title']) > 60 else article['title'])
        summary = escape_markdown(article.get('summary', 'N/A'))
        link = article['link']

        table_lines.append(f"| {pub_date_str} | {category} | {source} | {title} | {summary} | [Link]({link}) |")

    # Generate output to Daily Briefings folder
    # Archive dates: 2025-01-20 to 2026-01-20 go in Archive subfolder
    # Current dates: 2026-01-21 onwards go in main Daily Briefings folder
    today_date = datetime.now(UTC).date()
    today = today_date.strftime("%Y-%m-%d")

    archive_start = datetime(2025, 1, 20, tzinfo=UTC).date()
    archive_end = datetime(2026, 1, 20, tzinfo=UTC).date()

    briefings_dir = os.path.join(base_dir, "Daily Briefings")
    if archive_start <= today_date <= archive_end:
        briefings_dir = os.path.join(briefings_dir, "Archive")

    os.makedirs(briefings_dir, exist_ok=True)
    filename = os.path.join(briefings_dir, f"{today}.md")

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 🗞️ Daily Briefing: {today}\n\n")
        f.write(f"*Generated at {datetime.now(UTC).strftime('%H:%M')} UTC*\n\n")
        f.write(f"**Total Articles:** {len(all_articles)}\n\n")
        f.write("---\n\n")
        f.write("\n".join(table_lines))
        f.write("\n")

    print(f"\nSuccess! Created {filename}")
    print(f"{len(all_articles)} articles summarized.")


if __name__ == "__main__":
    main()
