"""应用配置（环境变量）。"""

import os
from dataclasses import dataclass


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    auto_sync_on_startup: bool
    bootstrap_recent_news_on_startup: bool
    sync_admin_token: str
    scheduled_sync_interval_hours: int
    scheduled_sync_timezone: str
    expose_api_docs: bool


def get_settings() -> Settings:
    return Settings(
        auto_sync_on_startup=_truthy_env("AUTO_SYNC_ON_STARTUP", "0"),
        bootstrap_recent_news_on_startup=_truthy_env("BOOTSTRAP_RECENT_NEWS_ON_STARTUP", "1"),
        sync_admin_token=os.getenv("SYNC_ADMIN_TOKEN", "").strip(),
        scheduled_sync_interval_hours=max(1, int(os.getenv("SCHEDULED_SYNC_INTERVAL_HOURS", "1"))),
        scheduled_sync_timezone=os.getenv("SCHEDULED_SYNC_TIMEZONE", "Asia/Shanghai").strip()
        or "Asia/Shanghai",
        expose_api_docs=_truthy_env("EXPOSE_API_DOCS", "1"),
    )
