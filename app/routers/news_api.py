"""JSON API：新闻与 AI 输出。"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.ai_summary import generate_questions, generate_summary
from app.news_data import (
    attach_isoformat_published_at,
    group_by_month,
    news_as_dict,
    query_news,
    today_news,
    yesterday_news,
)

router = APIRouter(prefix="/api", tags=["新闻与 AI API"])


@router.get("/news")
async def api_news(year: Optional[int] = Query(default=None)):
    news_items, years = query_news(year=year)
    data = news_as_dict(news_items)
    attach_isoformat_published_at(data)
    return JSONResponse({"years": years, "items": data})


@router.get("/news/today")
async def api_news_today():
    news_items, _ = query_news(year=None)
    today_items, today_title = today_news(news_items)
    data = news_as_dict(today_items)
    attach_isoformat_published_at(data)
    return JSONResponse({"title": today_title, "items": data})


@router.get("/news/yesterday")
async def api_news_yesterday():
    news_items, _ = query_news(year=None)
    yesterday_items, yesterday_title = yesterday_news(news_items)
    data = news_as_dict(yesterday_items)
    attach_isoformat_published_at(data)
    return JSONResponse({"title": yesterday_title, "items": data})


@router.get("/news/grouped-by-month")
async def api_news_grouped_by_month(year: Optional[int] = Query(default=None)):
    news_items, years = query_news(year=year)
    grouped = group_by_month(news_items)
    result: Dict[str, List[Dict[str, Any]]] = {}
    for month_label, items in grouped.items():
        data = news_as_dict(items)
        attach_isoformat_published_at(data)
        result[month_label] = data
    return JSONResponse({"years": years, "grouped_by_month": result})


@router.get("/news/past-two-years")
async def api_news_past_two_years():
    current_year = datetime.utcnow().year
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


@router.get("/ai/summary")
async def api_ai_summary(year: Optional[int] = Query(default=None)):
    """与首页「AI 总结」一致：基于当前筛选范围内的新闻文本生成要点。"""
    news_items, years = query_news(year=year)
    news_dicts = news_as_dict(news_items)
    lines = generate_summary(news_dicts)
    return JSONResponse(
        {
            "years": years,
            "year_filter": year,
            "summary": lines,
        }
    )


@router.get("/ai/questions")
async def api_ai_questions(year: Optional[int] = Query(default=None)):
    """与首页「公考风格练习题」一致：基于当前筛选范围内的新闻生成题目。"""
    news_items, years = query_news(year=year)
    news_dicts = news_as_dict(news_items)
    questions = generate_questions(news_dicts)
    return JSONResponse(
        {
            "years": years,
            "year_filter": year,
            "questions": questions,
        }
    )
