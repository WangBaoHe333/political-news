"""FastAPI 应用入口。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import init_db
from app.routers import news_api, sync_routes, web
from app.sync_service import fetch_and_save_news, reset_stale_sync_state
from app.tasks import setup_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    reset_stale_sync_state()
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("定时任务调度器已启动")
    settings = get_settings()
    if not settings.auto_sync_on_startup:
        logger.info("Startup auto sync is disabled; serving cached database content only.")
    else:
        try:
            fetch_and_save_news(months=24, max_pages=260, max_items=700)
        except Exception as exc:
            logger.exception("Startup bootstrap failed: %s", exc)
    yield
    scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    application = FastAPI(
        title="时政资料库 / Political News",
        description="中国政府网时政聚合、按月归档、年份筛选与关键词搜索。",
        version="1.0.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "页面", "description": "HTML 阅读界面"},
            {"name": "新闻 API", "description": "JSON 接口（支持年份、关键词与时间维度）"},
            {"name": "同步", "description": "数据抓取与后台任务"},
        ],
    )
    application.include_router(web.router)
    application.include_router(news_api.router)
    application.include_router(sync_routes.router)
    return application


app = create_app()
