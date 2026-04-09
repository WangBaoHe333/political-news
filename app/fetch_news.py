import feedparser
from app.database import SessionLocal
from app.models import News

RSS_URL = "https://feeds.bbci.co.uk/news/politics/rss.xml"


def fetch_news():
    feed = feedparser.parse(RSS_URL)
    news_items = []

    for entry in feed.entries:
        news_items.append({
            "title": entry.title,
            "link": entry.link,
            "summary": entry.summary,
            "published": entry.published
        })

    return news_items


def save_news_to_db(news_items):
    db = SessionLocal()
    for item in news_items:
        db_news = News(
            title=item["title"],
            link=item["link"],
            summary=item["summary"],
            published=item["published"]
        )
        db.add(db_news)
    db.commit()
    db.close()