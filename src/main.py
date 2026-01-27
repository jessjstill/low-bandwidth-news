"""
Low-Bandwidth News Aggregator
Fetches RSS/Atom feeds and podcast feeds, then uses Claude to create a daily briefing.
Outputs a Markdown table with one row per article.
"""

import os
import sys
import re
import ssl
import time
import argparse
from collections import defaultdict
import pandas as pd
import feedparser
import requests
import anthropic
import trafilatura
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Timezone
UTC = ZoneInfo("UTC")

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
    """Format publication date as MM-DD-YYYY / HH:MM UTC."""
    if not pub_date:
        return "N/A"
    try:
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=UTC)
        pub_utc = pub_date.astimezone(UTC)
        return pub_utc.strftime("%m-%d-%Y / %H:%M UTC")
    except:
        return pub_date.strftime("%m-%d-%Y / %H:%M")


def fetch_feed_content(url: str) -> feedparser.FeedParserDict:
    """Fetch and parse a feed, handling SSL certificate issues."""
    # First try direct parsing
    feed = feedparser.parse(url)

    # If SSL error, retry with requests (which can skip verification)
    if feed.bozo and 'CERTIFICATE_VERIFY_FAILED' in str(feed.bozo_exception):
        try:
            response = requests.get(url, verify=False, timeout=30)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except requests.RequestException as e:
            # Return the original failed feed
            pass

    return feed


def fetch_rss(url: str, category: str, source_name: str, max_items: int = 50, fetch_all: bool = False) -> list:
    """Fetch standard RSS/Atom feeds. Returns list of article dicts."""
    try:
        feed = fetch_feed_content(url)
        if feed.bozo and not feed.entries:
            return []

        articles = []
        entries = feed.entries if fetch_all else feed.entries[:max_items]
        for entry in entries:
            pub_date = parse_pub_date(entry)
            if not fetch_all and not is_today(pub_date):
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


def fetch_atom(url: str, category: str, source_name: str, max_items: int = 50, fetch_all: bool = False) -> list:
    """Fetch Atom feeds (like ArXiv API). Returns list of article dicts."""
    try:
        feed = fetch_feed_content(url)
        articles = []

        entries = feed.entries if fetch_all else feed.entries[:max_items]
        for entry in entries:
            pub_date = parse_pub_date(entry)
            if not fetch_all and not is_today(pub_date):
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


def fetch_podcast(url: str, category: str, source_name: str, max_items: int = 50, fetch_all: bool = False) -> list:
    """Fetch podcast RSS feeds. Returns list of episode dicts."""
    try:
        feed = fetch_feed_content(url)
        articles = []

        entries = feed.entries if fetch_all else feed.entries[:max_items]
        for entry in entries:
            pub_date = parse_pub_date(entry)
            if not fetch_all and not is_today(pub_date):
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


def fetch_content(url: str, feed_type: str, category: str, source_name: str, fetch_all: bool = False) -> list:
    """Route to appropriate fetcher based on feed type."""
    feed_type = (feed_type or 'rss').lower().strip()

    if feed_type == 'atom':
        return fetch_atom(url, category, source_name, fetch_all=fetch_all)
    elif feed_type == 'podcast':
        return fetch_podcast(url, category, source_name, fetch_all=fetch_all)
    elif feed_type == 'scrape':
        return fetch_scrape(url, category, source_name)
    else:
        return fetch_rss(url, category, source_name, fetch_all=fetch_all)


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


def group_articles_by_date(articles: list) -> dict:
    """Group articles by their publication date (YYYY-MM-DD)."""
    grouped = defaultdict(list)
    for article in articles:
        pub_date = article.get('pub_date')
        if pub_date:
            date_key = pub_date.astimezone(UTC).date().strftime("%Y-%m-%d")
        else:
            date_key = "unknown"
        grouped[date_key].append(article)
    return grouped


def write_briefing(articles: list, date_str: str, output_dir: str) -> str:
    """Write a daily briefing markdown file for a specific date."""
    # Sort by publication date (newest first)
    articles.sort(key=lambda x: (x.get('pub_date') or datetime.min.replace(tzinfo=UTC)), reverse=True)

    # Create table
    table_lines = [
        "| Date/Time | Category | Source | Title | Summary | Link |",
        "|-----------|----------|--------|-------|---------|------|"
    ]

    for article in articles:
        pub_date_str = format_pub_date(article.get('pub_date'))
        category = escape_markdown(article['category'])
        source = escape_markdown(article['source'])
        title = escape_markdown(article['title'][:60] + '...' if len(article['title']) > 60 else article['title'])
        summary = escape_markdown(article.get('summary', 'N/A'))
        link = article['link']

        table_lines.append(f"| {pub_date_str} | {category} | {source} | {title} | {summary} | [Link]({link}) |")

    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{date_str}.md")

    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# 🗞️ Daily Briefing: {date_str}\n\n")
        f.write(f"*Generated at {datetime.now(UTC).strftime('%H:%M')} UTC*\n\n")
        f.write(f"**Total Articles:** {len(articles)}\n\n")
        f.write("---\n\n")
        f.write("\n".join(table_lines))
        f.write("\n")

    return filename


def main():
    parser = argparse.ArgumentParser(description="Low-Bandwidth News Aggregator")
    parser.add_argument('--fetch-all', action='store_true',
                        help='Fetch all available articles (not just today) and create separate briefings by date')
    args = parser.parse_args()

    fetch_all = args.fetch_all

    print("Starting News Aggregator...")
    if fetch_all:
        print("Mode: FETCH ALL (historical)")
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

        articles = fetch_content(url, feed_type, category, source_name, fetch_all=fetch_all)
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

    # Output directory
    briefings_dir = os.path.join(base_dir, "Daily Briefings")

    if fetch_all:
        # Group by date and write separate files
        print("\nGrouping articles by date...")
        grouped = group_articles_by_date(all_articles)

        # Sort dates (newest first)
        sorted_dates = sorted(grouped.keys(), reverse=True)
        print(f"Found articles across {len(sorted_dates)} different dates")

        print("\nWriting briefings...")
        for date_str in sorted_dates:
            articles = grouped[date_str]
            if date_str == "unknown":
                print(f"   Skipping {len(articles)} articles with unknown dates")
                continue
            filename = write_briefing(articles, date_str, briefings_dir)
            print(f"   {date_str}: {len(articles)} articles -> {filename}")

        print(f"\nSuccess! Created {len(sorted_dates)} daily briefings")
        print(f"Total: {len(all_articles)} articles summarized.")
    else:
        # Original behavior: single file for today
        print("\nBuilding Markdown table...")

        today_date = datetime.now(UTC).date()
        today = today_date.strftime("%Y-%m-%d")

        filename = write_briefing(all_articles, today, briefings_dir)

        print(f"\nSuccess! Created {filename}")
        print(f"{len(all_articles)} articles summarized.")


if __name__ == "__main__":
    main()
