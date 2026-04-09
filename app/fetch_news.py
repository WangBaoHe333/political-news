import logging
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

import feedparser
from app.database import SessionLocal
from app.models import News

DEFAULT_RSS_URL = "https://feeds.bbci.co.uk/news/politics/rss.xml"
DEFAULT_TIMEOUT = 10

logger = logging.getLogger(__name__)


def fetch_news():
    rss_url = os.getenv("RSS_URL", DEFAULT_RSS_URL)
    timeout = int(os.getenv("RSS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT))
    request = Request(rss_url, headers={"User-Agent": "political-news/1.0"})

    try:
        with urlopen(request, timeout=timeout) as response:
            feed = feedparser.parse(response.read())
    except (TimeoutError, URLError, OSError) as exc:
        logger.warning("Failed to fetch RSS feed from %s: %s", rss_url, exc)
        return []

    news_items = []

    for entry in feed.entries:
        news_items.append({
            "title": getattr(entry, "title", "Untitled"),
            "link": getattr(entry, "link", ""),
            "summary": getattr(entry, "summary", ""),
            "published": getattr(entry, "published", "")
        })

    return news_items


def save_news_to_db(news_items):
    db = SessionLocal()
    saved_count = 0

    try:
        for item in news_items:
            if not item["link"]:
                continue

            existing_news = db.query(News).filter(News.link == item["link"]).first()
            if existing_news:
                continue

            db_news = News(
                title=item["title"],
                link=item["link"],
                summary=item["summary"],
                published=item["published"]
            )
            db.add(db_news)
            saved_count += 1

        db.commit()
        return saved_count
    finally:
        db.close()
