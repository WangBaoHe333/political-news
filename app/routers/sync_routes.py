"""同步与回填相关路由。"""

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, RedirectResponse

from app.sync_service import (
    fetch_and_save_news,
    get_sync_status,
    start_background_sync,
    start_batched_backfill,
)

router = APIRouter(tags=["同步"])


@router.get("/sync")
async def sync_news(
    year: Optional[int] = Query(default=None),
    months: int = Query(default=12, ge=1, le=36),
    max_pages: Optional[int] = Query(default=None, ge=1, le=500),
    max_items: Optional[int] = Query(default=None, ge=1, le=1000),
):
    result = fetch_and_save_news(
        year=year, months=months, max_pages=max_pages, max_items=max_items
    )
    return JSONResponse(result)


@router.get("/sync-view")
async def sync_view(
    year: Optional[int] = Query(default=None),
    months: int = Query(default=12, ge=1, le=36),
    max_pages: Optional[int] = Query(default=None, ge=1, le=500),
    max_items: Optional[int] = Query(default=None, ge=1, le=1000),
):
    scope = f"{year}年" if year else f"近{months}个月"
    started = start_background_sync(scope, year=year, months=months, max_pages=max_pages, max_items=max_items)
    if started:
        status = f"{scope}后台同步已启动，请稍后刷新页面查看结果。"
    else:
        status = "已有后台同步任务在运行，请稍后刷新查看。"
    encoded_status = quote(status)
    redirect_url = f"/?sync_status={encoded_status}"
    if year:
        redirect_url = f"/?year={year}&sync_status={encoded_status}"
    return RedirectResponse(url=redirect_url, status_code=303)


@router.get("/sync-status")
async def sync_status_route():
    return JSONResponse(get_sync_status())


@router.get("/backfill-view")
async def backfill_view(
    months: int = Query(default=24, ge=1, le=36),
    batch_size: int = Query(default=3, ge=1, le=6),
    max_items: int = Query(default=150, ge=20, le=400),
):
    scope = f"近{months}个月分批回填"
    started = start_batched_backfill(scope, total_months=months, batch_size=batch_size, max_items=max_items)
    if started:
        status = f"{scope}已启动，每批 {batch_size} 个月。请稍后刷新页面查看进度。"
    else:
        status = "已有后台同步任务在运行，请稍后刷新查看。"
    encoded_status = quote(status)
    return RedirectResponse(url=f"/?sync_status={encoded_status}", status_code=303)


@router.get("/health")
async def health_check():
    """健康检查（根路径，兼容负载均衡与旧文档）。"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
