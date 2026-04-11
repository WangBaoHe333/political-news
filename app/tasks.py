from apscheduler.schedulers.background import BackgroundScheduler


def setup_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        "app.sync_service:fetch_and_save_news",
        "interval",
        hours=1,
        kwargs={"months": 1, "max_pages": 12, "max_items": 80},
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
    )
    return scheduler
