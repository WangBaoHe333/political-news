"""JSON API：新闻查询。"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from zoneinfo import ZoneInfo

from app.news_data import (
    attach_isoformat_published_at,
    group_by_month,
    news_as_dict,
    query_news,
    today_news,
    yesterday_news,
)

router = APIRouter(prefix="/api", tags=["新闻 API"])
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@router.get("/news")
async def api_news(
    year: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None, description="按标题、正文、来源等字段搜索"),
    source: Optional[str] = Query(default=None, description="按来源筛选"),
    category: Optional[str] = Query(default=None, description="按时政分类筛选"),
    months: int = Query(default=24, ge=1, le=36),
):
    news_items, years = query_news(year=year, search=q, months=months, source=source, category=category)
    data = news_as_dict(news_items)
    attach_isoformat_published_at(data)
    return JSONResponse(
        {"years": years, "query": q or "", "source": source or "", "category": category or "", "items": data}
    )


@router.get("/news/today")
async def api_news_today():
    news_items, _ = query_news(year=None, months=24)
    today_items, today_title = today_news(news_items)
    data = news_as_dict(today_items)
    attach_isoformat_published_at(data)
    return JSONResponse({"title": today_title, "items": data})


@router.get("/news/yesterday")
async def api_news_yesterday():
    news_items, _ = query_news(year=None, months=24)
    yesterday_items, yesterday_title = yesterday_news(news_items)
    data = news_as_dict(yesterday_items)
    attach_isoformat_published_at(data)
    return JSONResponse({"title": yesterday_title, "items": data})


@router.get("/news/grouped-by-month")
async def api_news_grouped_by_month(
    year: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None, description="按标题、正文、来源等字段搜索"),
    source: Optional[str] = Query(default=None, description="按来源筛选"),
    category: Optional[str] = Query(default=None, description="按时政分类筛选"),
    months: int = Query(default=24, ge=1, le=36),
):
    news_items, years = query_news(year=year, search=q, months=months, source=source, category=category)
    grouped = group_by_month(news_items)
    result: Dict[str, List[Dict[str, Any]]] = {}
    for month_label, items in grouped.items():
        data = news_as_dict(items)
        attach_isoformat_published_at(data)
        result[month_label] = data
    return JSONResponse(
        {
            "years": years,
            "query": q or "",
            "source": source or "",
            "category": category or "",
            "grouped_by_month": result,
        }
    )


@router.get("/news/past-two-years")
async def api_news_past_two_years():
    current_year = datetime.now(LOCAL_TZ).year
    all_items = []
    for year in [current_year, current_year - 1]:
        news_items, _ = query_news(year=year)
        all_items.extend(news_items)

    all_items.sort(key=lambda x: x.published_at, reverse=True)

    data = news_as_dict(all_items)
    attach_isoformat_published_at(data)

    grouped = group_by_month(all_items)
    grouped_result: Dict[str, List[Dict[str, Any]]] = {}
    for month_label, items in grouped.items():
        month_data = news_as_dict(items)
        attach_isoformat_published_at(month_data)
        grouped_result[month_label] = month_data

    return JSONResponse(
        {
            "title": f"过去两年时政内容 ({current_year - 1}-{current_year})",
            "total_items": len(data),
            "items": data,
            "grouped_by_month": grouped_result,
        }
    )
