"""定时任务配置测试"""

from app.tasks import setup_scheduler


def test_scheduler_uses_shanghai_hourly_cron(monkeypatch):
    """默认应按北京时间整点每小时同步一次。"""
    monkeypatch.setenv("SCHEDULED_SYNC_INTERVAL_HOURS", "1")
    monkeypatch.setenv("SCHEDULED_SYNC_TIMEZONE", "Asia/Shanghai")

    scheduler = setup_scheduler()
    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert str(scheduler.timezone) == "Asia/Shanghai"
    assert str(job.trigger.timezone) == "Asia/Shanghai"

    fields = {field.name: str(field) for field in job.trigger.fields}
    assert fields["hour"] in {"*", "*/1"}
    assert fields["minute"] == "0"
