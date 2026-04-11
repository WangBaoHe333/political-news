"""应用配置（环境变量）。"""

import os
from dataclasses import dataclass


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    auto_sync_on_startup: bool

    @property
    def ai_enabled(self) -> bool:
        key = self.openai_api_key.strip()
        return bool(key and key != "your_openai_api_key_here")


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        auto_sync_on_startup=_truthy_env("AUTO_SYNC_ON_STARTUP", "0"),
    )
