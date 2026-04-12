"""FastAPI 应用入口。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import init_db
from app.news_data import count_news_records
from app.routers import news_api, sync_routes, web
from app.sync_service import has_recent_two_years_data, reset_stale_sync_state, start_background_sync
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

    db_is_empty = count_news_records() == 0
    should_bootstrap = db_is_empty or (
        settings.bootstrap_recent_news_on_startup and not has_recent_two_years_data(months=24)
    )

    if settings.auto_sync_on_startup or should_bootstrap:
        scope = "启动初始化同步"
        started = start_background_sync(scope, months=24, max_pages=260, max_items=700)
        if started:
            logger.info("Startup sync started in background.")
        else:
            logger.info("Startup sync skipped because another sync task is running.")
    else:
        logger.info("Startup auto sync is disabled and cached coverage looks sufficient.")
    yield
    scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="时政资料库 / Political News",
        description="中国政府网时政聚合、按月归档、年份筛选与关键词搜索。",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url="/redoc" if settings.expose_api_docs else None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
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
