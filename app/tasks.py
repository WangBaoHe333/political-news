from apscheduler.schedulers.background import BackgroundScheduler

def setup_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        "app.sync_service:fetch_and_save_news",
        "interval",
        hours=6,
        kwargs={"months": 1, "max_pages": 8, "max_items": 30}
    )
    return scheduler