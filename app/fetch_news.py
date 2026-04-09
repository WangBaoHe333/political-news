import logging
import os
import re
import json
from datetime import datetime, timedelta
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.database import SessionLocal
from app.models import News

logger = logging.getLogger(__name__)

DEFAULT_SOURCE = "gov_cn"
DEFAULT_CATEGORY = "时政"
LIST_BASE_URL = os.getenv("LIST_BASE_URL", "https://www.gov.cn/yaowen/")
LIST_JSON_URL = os.getenv("LIST_JSON_URL", "https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT_SECONDS", "12"))
DEFAULT_MAX_PAGES = int(os.getenv("SYNC_MAX_PAGES", "60"))
DEFAULT_MAX_ITEMS = int(os.getenv("SYNC_MAX_ITEMS", "400"))


def _normalize_text(value):
    value = unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _fetch_url(url):
    request = Request(url, headers={"User-Agent": "political-news/1.0"})
    with urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return response.read().decode("utf-8", errors="ignore")

def _extract_date(text):
    normalized = text.replace("/", "-").replace(".", "-")
    match = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", normalized)
    if not match:
        return None

    year, month, day = [int(value) for value in match.groups()]
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _parse_list_page(html_text, page_url):
    soup = BeautifulSoup(html_text, "html.parser")
    results = []
    seen_links = set()

    def find_date_for_anchor(anchor):
        candidates = []

        next_text = []
        for sibling in list(anchor.next_siblings)[:6]:
            text = _normalize_text(getattr(sibling, "get_text", lambda *args, **kwargs: str(sibling))(" ", strip=True) if hasattr(sibling, "get_text") else str(sibling))
            if text:
                next_text.append(text)
        if next_text:
            candidates.append(" ".join(next_text))

        for tag_name in ["li", "div", "section", "article", "ul"]:
            container = anchor.find_parent(tag_name)
            if container is not None:
                candidates.append(_normalize_text(container.get_text(" ", strip=True)))

        parent = anchor.parent
        hops = 0
        while parent is not None and hops < 6:
            candidates.append(_normalize_text(parent.get_text(" ", strip=True)))
            parent = parent.parent
            hops += 1

        for text in candidates:
            published_at = _extract_date(text)
            if published_at:
                return published_at
        return None

    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, anchor["href"])
        title = _normalize_text(anchor.get_text(" ", strip=True))
        if "content_" not in href or not title or href in seen_links:
            continue

        if "/yaowen/" not in href and "/zhuanti/" not in href:
            continue

        published_at = find_date_for_anchor(anchor)

        seen_links.add(href)
        results.append(
            {
                "source": DEFAULT_SOURCE,
                "category": DEFAULT_CATEGORY,
                "title": title,
                "link": href,
                "published": published_at.strftime("%Y-%m-%d") if published_at else "",
                "published_at": published_at,
                "summary": "",
                "content": "",
            }
        )

    return results


def _load_json_feed():
    raw = _fetch_url(LIST_JSON_URL)
    payload = json.loads(raw)
    if not isinstance(payload, list):
        return []

    items = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        title = _normalize_text(entry.get("TITLE") or entry.get("TITLE1") or entry.get("TI") or "")
        href = entry.get("URL") or entry.get("LINK") or ""
        published_text = (
            entry.get("DOCRELPUBTIME")
            or entry.get("PUBDATE")
            or entry.get("DATE")
            or entry.get("PT")
            or ""
        )
        published_at = _extract_date(str(published_text))

        if not title or not href:
            continue

        items.append(
            {
                "source": DEFAULT_SOURCE,
                "category": DEFAULT_CATEGORY,
                "title": title,
                "link": urljoin(LIST_BASE_URL, href),
                "published": published_at.strftime("%Y-%m-%d") if published_at else _normalize_text(str(published_text)),
                "published_at": published_at,
                "summary": "",
                "content": "",
            }
        )
    return items


def _parse_article_detail(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    full_text = _normalize_text(soup.get_text(" ", strip=True))
    published_at = _extract_date(full_text)
    blocks = []
    selectors = [
        ".pages_content p",
        ".article p",
        ".content p",
        ".TRS_Editor p",
        "main p",
    ]

    for selector in selectors:
        paragraphs = soup.select(selector)
        if paragraphs:
            blocks = paragraphs
            break

    if not blocks:
        blocks = soup.find_all("p")

    paragraphs = []
    for block in blocks:
        text = _normalize_text(block.get_text(" ", strip=True))
        if len(text) < 10:
            continue
        if any(token in text for token in ["责任编辑", "扫一扫", "打印", "关闭窗口"]):
            continue
        paragraphs.append(text)

    content = "\n".join(paragraphs[:20])
    summary = paragraphs[0] if paragraphs else ""
    return summary, content, published_at


def _target_range(year=None, months=12):
    now = datetime.utcnow()
    if year:
        return datetime(year, 1, 1), datetime(year, 12, 31, 23, 59, 59)
    start = now - timedelta(days=max(months, 1) * 30)
    return start, now


def fetch_news(year=None, months=12, max_pages=None, max_items=None):
    max_items = max_items or DEFAULT_MAX_ITEMS
    start_date, end_date = _target_range(year=year, months=months)

    news_items = []
    try:
        page_items = _load_json_feed()
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to fetch json feed %s: %s", LIST_JSON_URL, exc)
        return []

    for item in page_items:
        published_at = item["published_at"]
        if not published_at:
            try:
                article_html = _fetch_url(item["link"])
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                logger.warning("Failed to fetch article %s: %s", item["link"], exc)
                article_html = ""
            _, _, detail_date = _parse_article_detail(article_html) if article_html else ("", "", None)
            published_at = detail_date
            if not published_at:
                continue
            item["published_at"] = published_at
            item["published"] = published_at.strftime("%Y-%m-%d")

        if published_at > end_date:
            continue
        if published_at < start_date:
            continue

        try:
            article_html = _fetch_url(item["link"])
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            logger.warning("Failed to fetch article %s: %s", item["link"], exc)
            article_html = ""

        summary, content, detail_date = _parse_article_detail(article_html) if article_html else ("", "", None)
        if detail_date:
            item["published_at"] = detail_date
            item["published"] = detail_date.strftime("%Y-%m-%d")

        item["summary"] = summary or item["title"]
        item["content"] = content or summary or item["title"]
        news_items.append(item)

        if len(news_items) >= max_items:
            break

    news_items.sort(key=lambda item: item["published_at"], reverse=True)
    return news_items


def save_news_to_db(news_items):
    db = SessionLocal()
    saved_count = 0

    try:
        for item in news_items:
            existing_news = db.query(News).filter(News.link == item["link"]).first()
            if existing_news:
                existing_news.summary = item["summary"] or existing_news.summary
                existing_news.content = item["content"] or existing_news.content
                existing_news.published = item["published"]
                existing_news.published_at = item["published_at"]
                existing_news.year = item["published_at"].year
                existing_news.month = item["published_at"].month
                existing_news.source = item["source"]
                existing_news.category = item["category"]
                continue

            db.add(
                News(
                    source=item["source"],
                    category=item["category"],
                    title=item["title"],
                    link=item["link"],
                    summary=item["summary"],
                    content=item["content"],
                    published=item["published"],
                    published_at=item["published_at"],
                    year=item["published_at"].year,
                    month=item["published_at"].month,
                )
            )
            saved_count += 1

        db.commit()
        return saved_count
    finally:
        db.close()
