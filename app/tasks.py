from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings


def setup_scheduler():
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone=settings.scheduled_sync_timezone)
    scheduler.add_job(
        "app.sync_service:run_scheduled_sync",
        "cron",
        hour=f"*/{settings.scheduled_sync_interval_hours}",
        minute=0,
        kwargs={"months": 1, "max_pages": 12, "max_items": 80},
        id="hourly_news_sync",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=600,
        replace_existing=True,
    )
    return scheduler
