"""同步与回填相关路由。"""

from datetime import datetime
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, Query
from fastapi import HTTPException
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import get_settings
from app.sync_service import (
    get_sync_status,
    run_sync_now,
    start_background_sync,
    start_batched_backfill,
)

router = APIRouter(tags=["同步"])
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _ensure_sync_token(token: Optional[str]) -> None:
    required_token = get_settings().sync_admin_token
    if not required_token:
        return
    if token != required_token:
        raise HTTPException(status_code=403, detail="同步接口需要管理员令牌。")


@router.get("/sync")
async def sync_news(
    year: Optional[int] = Query(default=None),
    months: int = Query(default=12, ge=1, le=36),
    max_pages: Optional[int] = Query(default=None, ge=1, le=500),
    max_items: Optional[int] = Query(default=None, ge=1, le=1000),
    token: Optional[str] = Query(default=None),
    x_sync_token: Optional[str] = Header(default=None, alias="X-Sync-Token"),
):
    _ensure_sync_token(x_sync_token or token)
    try:
        result = run_sync_now(
            scope_label=f"{year}年手动同步" if year else f"近{months}个月手动同步",
            year=year,
            months=months,
            max_pages=max_pages,
            max_items=max_items,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步执行失败：{exc}") from exc

    if result is None:
        raise HTTPException(status_code=409, detail="已有同步任务在运行，请稍后再试。")
    return JSONResponse(result)


@router.get("/sync-view")
async def sync_view(
    year: Optional[int] = Query(default=None),
    months: int = Query(default=12, ge=1, le=36),
    max_pages: Optional[int] = Query(default=None, ge=1, le=500),
    max_items: Optional[int] = Query(default=None, ge=1, le=1000),
    token: Optional[str] = Query(default=None),
    x_sync_token: Optional[str] = Header(default=None, alias="X-Sync-Token"),
):
    _ensure_sync_token(x_sync_token or token)
    scope = f"{year}年" if year else f"近{months}个月"
    started = start_background_sync(scope, year=year, months=months, max_pages=max_pages, max_items=max_items)
    if started:
        status = f"{scope}后台同步已启动，请稍后刷新页面查看结果。"
    else:
        status = "已有后台同步任务在运行，请稍后刷新查看。"
    encoded_status = quote(status)
    return RedirectResponse(url=f"/status?sync_status={encoded_status}", status_code=303)


@router.get("/sync-status")
async def sync_status_route():
    return JSONResponse(get_sync_status())


@router.get("/backfill-view")
async def backfill_view(
    months: int = Query(default=24, ge=1, le=36),
    batch_size: int = Query(default=3, ge=1, le=6),
    max_items: int = Query(default=150, ge=20, le=400),
    token: Optional[str] = Query(default=None),
    x_sync_token: Optional[str] = Header(default=None, alias="X-Sync-Token"),
):
    _ensure_sync_token(x_sync_token or token)
    scope = f"近{months}个月分批回填"
    started = start_batched_backfill(scope, total_months=months, batch_size=batch_size, max_items=max_items)
    if started:
        status = f"{scope}已启动，每批 {batch_size} 个月。请稍后刷新页面查看进度。"
    else:
        status = "已有后台同步任务在运行，请稍后刷新查看。"
    encoded_status = quote(status)
    return RedirectResponse(url=f"/status?sync_status={encoded_status}", status_code=303)


@router.get("/health")
async def health_check():
    """健康检查（北京时间）。"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(LOCAL_TZ).isoformat(),
        "timezone": "Asia/Shanghai",
    }
