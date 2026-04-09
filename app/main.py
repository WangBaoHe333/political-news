from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from app.fetch_news import fetch_news, save_news_to_db
from app.ai_summary import generate_summary
from app.database import SessionLocal
from app.models import News

app = FastAPI()


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


@app.on_event("startup")
def fetch_and_save_news():
    news_items = fetch_news()
    save_news_to_db(news_items)


@app.on_event("shutdown")
def close_db():
    db = SessionLocal()
    db.close()