"""新闻查询与列表结构（供页面与 API 共用）。"""

from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_

from app.database import SessionLocal
from app.models import News

SOURCE_LABELS = {
    "gov_cn": "中国政府网",
    "people_cn": "人民网",
    "xinhuanet": "新华网",
    "chinanews": "中国新闻网",
    "cctv": "央视网",
    "mfa": "外交部",
    "sina": "新浪新闻",
}
SOURCE_TRUST_LABELS = {
    "gov_cn": "官方发布",
    "people_cn": "央媒报道",
    "xinhuanet": "央媒报道",
    "chinanews": "主流媒体",
    "cctv": "央媒报道",
    "mfa": "部委发布",
    "sina": "转载来源",
}
SOURCE_TRUST_NOTES = {
    "gov_cn": "国务院与政府系统公开发布内容，优先级最高。",
    "people_cn": "人民网时政频道原文或 RSS，同步后保留原文链接。",
    "xinhuanet": "新华网政治频道原文或 RSS，同步后保留原文链接。",
    "chinanews": "中国新闻网中国频道原文或 RSS，同步后保留原文链接。",
    "cctv": "央视网新闻频道公开发布内容，适合补足权威电视媒体口径。",
    "mfa": "外交部官网公开发布内容，适合补足外交与外事动态。",
    "sina": "仅作历史兼容展示，新同步流程默认不再纳入。",
}
CATEGORY_DEFINITIONS = OrderedDict(
    [
        ("yaowen", "要闻"),
        ("shizheng", "时政"),
        ("quanwei", "权威发布"),
        ("waijiao", "外交"),
        ("renshi", "人事"),
        ("guoji", "国际"),
        ("gangaotai", "港澳台"),
        ("junshi", "军事"),
    ]
)
CATEGORY_LABEL_TO_SLUG = {label: slug for slug, label in CATEGORY_DEFINITIONS.items()}
CATEGORY_ALIASES = {
    "国务院要闻": "要闻",
    "中国": "时政",
    "国内": "时政",
    "头条新闻": "外交",
}


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
    months: Optional[int] = 24,
    source: Optional[str] = None,
    category: Optional[str] = None,
) -> Tuple[List[News], List[int]]:
    db = SessionLocal()
    try:
        query = db.query(News)

        if year:
            query = query.filter(News.year == year)
        elif months is not None:
            start_date = datetime.utcnow() - timedelta(days=max(months, 1) * 30)
            query = query.filter(News.published_at >= start_date)

        search_filter = _build_search_filter(search or "")
        if search_filter is not None:
            query = query.filter(search_filter)

        if source:
            query = query.filter(News.source == source)

        if category:
            query = query.filter(News.category == normalize_category(category))

        news_items = query.order_by(News.published_at.desc()).all()
        years = [value[0] for value in db.query(News.year).distinct().order_by(News.year.desc()).all()]
        return news_items, years
    finally:
        db.close()


def get_news_by_id(news_id: int) -> Optional[News]:
    db = SessionLocal()
    try:
        return db.query(News).filter(News.id == news_id).first()
    finally:
        db.close()


def source_label(source: Optional[str]) -> str:
    if not source:
        return "未知来源"
    return SOURCE_LABELS.get(source, source)


def source_trust_label(source: Optional[str]) -> str:
    if not source:
        return "来源待确认"
    return SOURCE_TRUST_LABELS.get(source, "来源待确认")


def source_trust_note(source: Optional[str]) -> str:
    if not source:
        return "请以原文链接为准。"
    return SOURCE_TRUST_NOTES.get(source, "请以原文链接为准。")


def normalize_category(category: Optional[str]) -> str:
    value = (category or "").strip()
    if not value:
        return "时政"
    return CATEGORY_ALIASES.get(value, value)


def category_label(category: Optional[str]) -> str:
    return normalize_category(category)


def category_slug(category: Optional[str]) -> str:
    normalized = normalize_category(category)
    return CATEGORY_LABEL_TO_SLUG.get(normalized, "shizheng")


def category_from_slug(slug: str) -> str:
    return CATEGORY_DEFINITIONS.get(slug, "时政")


def get_year_counts(min_year: Optional[int] = None) -> Dict[int, int]:
    db = SessionLocal()
    try:
        query = db.query(News.year, func.count(News.id)).group_by(News.year).order_by(News.year.desc())
        if min_year is not None:
            query = query.filter(News.year >= min_year)
        return {year: count for year, count in query.all()}
    finally:
        db.close()


def count_news_records() -> int:
    db = SessionLocal()
    try:
        return db.query(func.count(News.id)).scalar() or 0
    finally:
        db.close()


def get_category_counts(
    *,
    year: Optional[int] = None,
    months: Optional[int] = 24,
    source: Optional[str] = None,
) -> Dict[str, int]:
    items, _ = query_news(year=year, months=months, source=source)
    counts: Dict[str, int] = {}
    for item in items:
        label = category_label(item.category)
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda entry: (-entry[1], CATEGORY_LABEL_TO_SLUG.get(entry[0], "zz"))))


def news_as_dict(news_items: List[News]) -> List[Dict[str, Any]]:
    return [
        {
            "id": item.id,
            "source": item.source,
            "category": category_label(item.category),
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


def today_news(news_items: List[News], limit: Optional[int] = 8) -> Tuple[List[News], str]:
    today = datetime.now(LOCAL_TZ).date()
    today_items = [item for item in news_items if item.published_at.date() == today]
    if limit is not None:
        today_items = today_items[:limit]
    return today_items, f"今日时政（{today.strftime('%Y-%m-%d')}）"


def yesterday_news(news_items: List[News], limit: Optional[int] = 8) -> Tuple[List[News], str]:
    yesterday = datetime.now(LOCAL_TZ).date() - timedelta(days=1)
    yesterday_items = [item for item in news_items if item.published_at.date() == yesterday]
    if limit is not None:
        yesterday_items = yesterday_items[:limit]
    return yesterday_items, f"昨日时政（{yesterday.strftime('%Y-%m-%d')}）"


def attach_isoformat_published_at(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for item in items:
        pa = item.get("published_at")
        if isinstance(pa, datetime):
            item["published_at"] = pa.isoformat()
    return items
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
