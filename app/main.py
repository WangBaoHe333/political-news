import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from app.fetch_news import fetch_news, save_news_to_db
from app.database import SessionLocal
from app.models import News

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


def fetch_and_save_news():
    news_items = fetch_news()
    saved_count = save_news_to_db(news_items)
    logger.info("Fetched %s items, saved %s new records", len(news_items), saved_count)
    return {"fetched": len(news_items), "saved": saved_count}


@app.get("/")
async def read_news():
    db = SessionLocal()
    news_items = db.query(News).order_by(News.published.desc()).limit(10).all()
    db.close()

    html_content = "<h1>Latest Political News</h1><ul>"
    for news in news_items:
        html_content += f"<li><a href='{news.link}'>{news.title}</a><br>{news.summary}</li>"
    html_content += "</ul>"

    return HTMLResponse(content=html_content, status_code=200)


@app.get("/refresh")
async def refresh_news():
    return fetch_and_save_news()


@app.on_event("startup")
def fetch_news_on_startup():
    try:
        fetch_and_save_news()
    except Exception as exc:
        logger.exception("Startup news fetch failed: %s", exc)


@app.on_event("shutdown")
def close_db():
    db = SessionLocal()
    db.close()
