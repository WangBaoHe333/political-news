"""新闻查询与列表结构（供页面与 API 共用）。"""

from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import or_

from app.database import SessionLocal
from app.models import News


def _build_search_filter(query_text: str):
    normalized = (query_text or "").strip()
    if not normalized:
        return None

    pattern = f"%{normalized}%"
    return or_(
        News.title.ilike(pattern),
        News.summary.ilike(pattern),
        News.content.ilike(pattern),
        News.link.ilike(pattern),
        News.source.ilike(pattern),
        News.category.ilike(pattern),
        News.published.ilike(pattern),
    )


def query_news(
    year: Optional[int] = None,
    search: Optional[str] = None,
    months: int = 24,
) -> Tuple[List[News], List[int]]:
    db = SessionLocal()
    try:
        query = db.query(News)

        if year:
            query = query.filter(News.year == year)
        else:
            start_date = datetime.utcnow() - timedelta(days=max(months, 1) * 30)
            query = query.filter(News.published_at >= start_date)

        search_filter = _build_search_filter(search or "")
        if search_filter is not None:
            query = query.filter(search_filter)

        news_items = query.order_by(News.published_at.desc()).all()
        years = [value[0] for value in db.query(News.year).distinct().order_by(News.year.desc()).all()]
        return news_items, years
    finally:
        db.close()


def news_as_dict(news_items: List[News]) -> List[Dict[str, Any]]:
    return [
        {
            "id": item.id,
            "source": item.source,
            "category": item.category,
            "title": item.title,
            "link": item.link,
            "summary": item.summary,
            "content": item.content,
            "published": item.published,
            "published_at": item.published_at,
            "year": item.year,
            "month": item.month,
        }
        for item in news_items
    ]


def group_by_month(news_items: List[News]) -> "OrderedDict[str, List[News]]":
    groups: "OrderedDict[str, List[News]]" = OrderedDict()
    for item in news_items:
        key = item.published_at.strftime("%Y年%m月")
        groups.setdefault(key, []).append(item)
    return groups


def latest_news_date(news_items: List[News]) -> Optional[datetime]:
    if not news_items:
        return None
    return max(item.published_at for item in news_items)


def today_news(news_items: List[News]) -> Tuple[List[News], str]:
    today = datetime.now(LOCAL_TZ).date()
    today_items = [item for item in news_items if item.published_at.date() == today]
    return today_items[:8], f"今日时政（{today.strftime('%Y-%m-%d')}）"


def yesterday_news(news_items: List[News]) -> Tuple[List[News], str]:
    yesterday = datetime.now(LOCAL_TZ).date() - timedelta(days=1)
    yesterday_items = [item for item in news_items if item.published_at.date() == yesterday]
    return yesterday_items[:8], f"昨日时政（{yesterday.strftime('%Y-%m-%d')}）"


def attach_isoformat_published_at(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for item in items:
        pa = item.get("published_at")
        if isinstance(pa, datetime):
            item["published_at"] = pa.isoformat()
    return items
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
