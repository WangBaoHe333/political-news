from apscheduler.schedulers.background import BackgroundScheduler
from app.fetch_news import fetch_news, save_news_to_db
from app.ai_summary import generate_summary

scheduler = BackgroundScheduler()

def fetch_and_summarize():
    news_items = fetch_news()
    for item in news_items:
        summary = generate_summary(item["summary"])
        item["summary"] = summary
    save_news_to_db(news_items)

# 每小时抓取一次新闻并生成摘要
scheduler.add_job(fetch_and_summarize, 'interval', hours=1)
scheduler.start()