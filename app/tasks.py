from apscheduler.schedulers.background import BackgroundScheduler

from app.main import fetch_and_save_news

scheduler = BackgroundScheduler()
scheduler.add_job(fetch_and_save_news, "interval", hours=6, kwargs={"months": 1, "max_pages": 8, "max_items": 30})
