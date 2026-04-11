import logging
import os
import re
import json
import time
import random
import ssl
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from bs4 import BeautifulSoup
import feedparser

from app.database import SessionLocal
from app.models import News

logger = logging.getLogger(__name__)

DEFAULT_SOURCE = "gov_cn"
DEFAULT_CATEGORY = "时政"
LIST_BASE_URL = os.getenv("LIST_BASE_URL", "https://www.gov.cn/yaowen/")
LIST_JSON_URL = os.getenv("LIST_JSON_URL", "https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json")
LIST_ARCHIVE_BASE_URL = os.getenv("LIST_ARCHIVE_BASE_URL", "https://www.gov.cn/yaowen/liebiao/")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT_SECONDS", "30"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
DEFAULT_MAX_PAGES = int(os.getenv("SYNC_MAX_PAGES", "260"))
DEFAULT_MAX_ITEMS = int(os.getenv("SYNC_MAX_ITEMS", "400"))
CURATED_RSS_SOURCES = [
    {
        "source": "people_cn",
        "category": "时政",
        "feed_url": "http://www.people.com.cn/rss/politics.xml",
        "base_url": "https://politics.people.com.cn/",
        "max_entries": 20,
    },
    {
        "source": "people_cn",
        "category": "国际",
        "feed_url": "http://www.people.com.cn/rss/world.xml",
        "base_url": "https://world.people.com.cn/",
        "max_entries": 20,
    },
    {
        "source": "people_cn",
        "category": "港澳台",
        "feed_url": "http://www.people.com.cn/rss/haixia.xml",
        "base_url": "https://tw.people.com.cn/",
        "max_entries": 20,
    },
    {
        "source": "people_cn",
        "category": "军事",
        "feed_url": "http://www.people.com.cn/rss/military.xml",
        "base_url": "https://military.people.com.cn/",
        "max_entries": 20,
    },
    {
        "source": "xinhuanet",
        "category": "时政",
        "feed_url": "http://www.xinhuanet.com/politics/news_politics.xml",
        "base_url": "https://www.news.cn/",
        "max_entries": 24,
    },
    {
        "source": "chinanews",
        "category": "时政",
        "feed_url": "https://www.chinanews.com.cn/rss/china.xml",
        "base_url": "https://www.chinanews.com.cn/",
        "max_entries": 20,
    },
    {
        "source": "chinanews",
        "category": "国际",
        "feed_url": "https://www.chinanews.com.cn/rss/world.xml",
        "base_url": "https://www.chinanews.com.cn/",
        "max_entries": 20,
    },
]
CURATED_HTML_SOURCES = [
    {
        "source": "xinhuanet",
        "category": "时政",
        "list_urls": ["https://www.news.cn/politics/"],
        "base_url": "https://www.news.cn/",
        "link_keywords": ("/politics/",),
        "article_patterns": (".shtml", "/20"),
        "max_entries": 36,
    },
    {
        "source": "cctv",
        "category": "时政",
        "list_urls": ["https://news.cctv.com/china/"],
        "base_url": "https://news.cctv.com/",
        "link_keywords": (),
        "article_patterns": (".shtml", "/20"),
        "max_entries": 36,
    },
    {
        "source": "mfa",
        "category": "外交",
        "list_urls": [
            "https://www.mfa.gov.cn/web/ttxw/index.shtml",
            "https://www.mfa.gov.cn/web/ttxw/index_1.shtml",
            "https://www.mfa.gov.cn/web/ttxw/index_2.shtml",
            "https://www.mfa.gov.cn/web/ttxw/index_3.shtml",
        ],
        "base_url": "https://www.mfa.gov.cn/",
        "link_keywords": ("/web/ttxw/",),
        "article_patterns": (".shtml",),
        "max_entries": 40,
    },
]
TRUSTED_SOURCE_RULES = {
    "gov_cn": {
        "domains": ("gov.cn",),
        "min_content_length": 18,
    },
    "people_cn": {
        "domains": ("people.com.cn",),
        "min_content_length": 18,
    },
    "xinhuanet": {
        "domains": ("xinhuanet.com", "news.cn"),
        "min_content_length": 18,
    },
    "chinanews": {
        "domains": ("chinanews.com.cn",),
        "min_content_length": 18,
    },
    "cctv": {
        "domains": ("news.cctv.com",),
        "min_content_length": 18,
    },
    "mfa": {
        "domains": ("mfa.gov.cn",),
        "min_content_length": 18,
    },
}


def _normalize_text(value):
    value = unescape(value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _hostname_matches(hostname, allowed_domains):
    if not hostname:
        return False
    hostname = hostname.lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)


def _is_allowed_source_link(source, link):
    rule = TRUSTED_SOURCE_RULES.get(source)
    if not rule:
        return False
    parsed = urlparse(link)
    return _hostname_matches(parsed.hostname, rule["domains"])


def _is_reliable_item(item):
    published_at = item.get("published_at")
    if not published_at:
        return False
    if published_at > datetime.utcnow() + timedelta(days=1):
        return False
    if not _is_allowed_source_link(item.get("source"), item.get("link", "")):
        return False

    content = _normalize_text(item.get("content") or "")
    summary = _normalize_text(item.get("summary") or "")
    min_length = TRUSTED_SOURCE_RULES.get(item.get("source"), {}).get("min_content_length", 40)
    return len(content) >= min_length or len(summary) >= min_length


def _fetch_url(url):
    last_error = None
    # 创建不验证SSL证书的上下文
    context = ssl._create_unverified_context()
    for attempt in range(HTTP_RETRIES + 1):
        try:
            request = Request(url, headers={"User-Agent": "political-news/1.0"})
            with urlopen(request, timeout=HTTP_TIMEOUT, context=context) as response:
                return response.read().decode("utf-8", errors="ignore")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= HTTP_RETRIES:
                logger.warning("Failed to fetch %s after %d attempts: %s", url, attempt + 1, exc)
                raise
            # 指数退避 + 随机抖动
            base_delay = 1.5
            delay = base_delay * (2 ** attempt) + random.uniform(0, base_delay * 0.1)
            logger.info("Retry %d for %s after %.2f seconds: %s", attempt + 1, url, delay, exc)
            time.sleep(delay)
    raise last_error


def _build_archive_url(page_number):
    return urljoin(LIST_ARCHIVE_BASE_URL, f"home_{page_number}.htm")


def _extract_date(text):
    """从文本中提取日期，支持多种格式"""
    if not text:
        return None

    # 模式列表：按优先级尝试
    patterns = [
        # YYYY-MM-DD
        r"(20\d{2})[-/年\.](\d{1,2})[-/月\.](\d{1,2})",
        # YYYY-MM
        r"(20\d{2})[-/年\.](\d{1,2})",
        # 中文日期：YYYY年MM月DD日
        r"(20\d{2})年(\d{1,2})月(\d{1,2})日",
        # 月份英文简写：DD Mon YYYY
        r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(20\d{2})",
    ]

    month_map = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
    }

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        groups = match.groups()
        if len(groups) == 3:
            # 处理三种情况：YYYY-MM-DD 或 中文日期 或 DD Mon YYYY
            if groups[1].isalpha():
                # DD Mon YYYY
                day, month_str, year = int(groups[0]), groups[1], int(groups[2])
                month = month_map.get(month_str.capitalize())
            else:
                # YYYY-MM-DD 或中文日期
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
        elif len(groups) == 2:
            # YYYY-MM
            year, month = int(groups[0]), int(groups[1])
            day = 1  # 默认第一天
        else:
            continue

        try:
            return datetime(year, month, day)
        except ValueError:
            continue

    # 如果所有模式都失败，尝试更宽松的匹配
    # 查找任何看起来像日期的数字组合
    fallback = re.search(r"(20\d{2})[^\d]*(\d{1,2})[^\d]*(\d{1,2})", text)
    if fallback:
        try:
            year, month, day = [int(x) for x in fallback.groups()]
            return datetime(year, month, day)
        except ValueError:
            pass

    return None


def _classify_category(source, default_category, title):
    normalized_title = _normalize_text(title)
    if source == "mfa":
        return "外交"
    if any(keyword in normalized_title for keyword in ["任免", "任命", "免去", "辞去", "履新"]):
        return "人事"
    if any(
        keyword in normalized_title
        for keyword in ["受权发布", "全文", "公报", "白皮书", "决定", "方案", "规定", "意见", "联合声明"]
    ):
        return "权威发布"
    if default_category in {"中国", "国内"}:
        return "时政"
    return default_category or DEFAULT_CATEGORY


def _parse_generic_list_page(html_text, page_url, source_config):
    soup = BeautifulSoup(html_text, "html.parser")
    results = []
    seen_links = set()
    link_keywords = source_config.get("link_keywords", ())
    article_patterns = source_config.get("article_patterns", ())
    max_entries = source_config.get("max_entries", 30)

    def find_date_for_anchor(anchor):
        candidates = []
        next_text = []
        for sibling in list(anchor.next_siblings)[:6]:
            if hasattr(sibling, "get_text"):
                text = _normalize_text(sibling.get_text(" ", strip=True))
            else:
                text = _normalize_text(str(sibling))
            if text:
                next_text.append(text)
        if next_text:
            candidates.append(" ".join(next_text))

        parent = anchor.parent
        hops = 0
        while parent is not None and hops < 5:
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
        if len(title) < 8 or href in seen_links:
            continue
        if not _is_allowed_source_link(source_config["source"], href):
            continue
        if link_keywords and not any(keyword in urlparse(href).path for keyword in link_keywords):
            continue
        if article_patterns and not any(pattern in urlparse(href).path for pattern in article_patterns):
            continue
        if href.endswith((".jpg", ".png", ".mp4", ".pdf")):
            continue

        seen_links.add(href)
        results.append(
            {
                "source": source_config["source"],
                "category": _classify_category(source_config["source"], source_config.get("category", DEFAULT_CATEGORY), title),
                "title": title,
                "link": href,
                "published": "",
                "published_at": find_date_for_anchor(anchor),
                "summary": "",
                "content": "",
            }
        )
        if len(results) >= max_entries:
            break

    return results


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
                "category": _classify_category(DEFAULT_SOURCE, "要闻", title),
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
                "category": _classify_category(DEFAULT_SOURCE, "要闻", title),
                "title": title,
                "link": urljoin(LIST_BASE_URL, href),
                "published": published_at.strftime("%Y-%m-%d") if published_at else _normalize_text(str(published_text)),
                "published_at": published_at,
                "summary": "",
                "content": "",
            }
        )
    return items


def _parse_feed_entries(source_config, raw_xml):
    parsed = feedparser.parse(raw_xml.encode("utf-8"))
    items = []
    for entry in parsed.entries[: source_config.get("max_entries", 20)]:
        title = _normalize_text(entry.get("title", ""))
        href = entry.get("link", "")
        if not title or not href:
            continue
        full_link = urljoin(source_config.get("base_url", ""), href)
        if not _is_allowed_source_link(source_config["source"], full_link):
            continue

        published_text = (
            entry.get("published")
            or entry.get("updated")
            or entry.get("created")
            or entry.get("pubDate")
            or ""
        )
        summary = _normalize_text(
            entry.get("summary")
            or entry.get("description")
            or (
                entry.get("content", [{}])[0].get("value", "")
                if isinstance(entry.get("content"), list) and entry.get("content")
                else ""
            )
        )
        published_at = _extract_date(f"{published_text} {summary}")
        items.append(
            {
                "source": source_config["source"],
                "category": _classify_category(
                    source_config["source"],
                    source_config.get("category", DEFAULT_CATEGORY),
                    title,
                ),
                "title": title,
                "link": full_link,
                "published": published_at.strftime("%Y-%m-%d") if published_at else _normalize_text(published_text),
                "published_at": published_at,
                "summary": summary,
                "content": summary,
            }
        )
    return items


def _load_external_source_feeds(progress_callback=None):
    items = []
    source_configs = CURATED_RSS_SOURCES

    for source_config in source_configs:
        try:
            raw_xml = _fetch_url(source_config["feed_url"])
            feed_items = _parse_feed_entries(source_config, raw_xml)
            items.extend(feed_items)
            if progress_callback:
                progress_callback(
                    {
                        "stage": "rss",
                        "source": source_config["source"],
                        "matched": len(feed_items),
                        "feed_url": source_config["feed_url"],
                    }
                )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            logger.warning("Failed to load feed %s: %s", source_config["feed_url"], exc)
    return items


def _load_external_html_sources(progress_callback=None):
    items = []
    for source_config in CURATED_HTML_SOURCES:
        source_items = []
        for list_url in source_config.get("list_urls", []):
            try:
                html_text = _fetch_url(list_url)
                parsed_items = _parse_generic_list_page(html_text, list_url, source_config)
                source_items.extend(parsed_items)
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                logger.warning("Failed to load source page %s: %s", list_url, exc)

        deduped = []
        seen_links = set()
        for item in source_items:
            if item["link"] in seen_links:
                continue
            seen_links.add(item["link"])
            deduped.append(item)

        items.extend(deduped)
        if progress_callback:
            progress_callback(
                {
                    "stage": "source_page",
                    "source": source_config["source"],
                    "matched": len(deduped),
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
        ".rm_txt_con p",
        ".article-content p",
        ".content_area p",
        ".left_zw p",
        ".news-article p",
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


def _target_range(year=None, months=12, start_date=None, end_date=None):
    if start_date and end_date:
        return start_date, end_date
    now = datetime.utcnow()
    if year:
        return datetime(year, 1, 1), datetime(year, 12, 31, 23, 59, 59)
    start = now - timedelta(days=max(months, 1) * 30)
    return start, now


def fetch_news(year=None, months=12, max_pages=None, max_items=None, start_date=None, end_date=None, progress_callback=None):
    max_pages = max_pages or DEFAULT_MAX_PAGES
    max_items = max_items or DEFAULT_MAX_ITEMS
    start_date, end_date = _target_range(year=year, months=months, start_date=start_date, end_date=end_date)

    news_items = []
    seen_links = set()

    def append_items(items):
        for item in items:
            if item["link"] in seen_links:
                continue
            seen_links.add(item["link"])
            news_items.append(item)
            if len(news_items) >= max_items:
                return True
        return False

    try:
        page_items = _load_json_feed()
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to fetch json feed %s: %s", LIST_JSON_URL, exc)
        page_items = []

    page_items.extend(_load_external_source_feeds(progress_callback=progress_callback))
    page_items.extend(_load_external_html_sources(progress_callback=progress_callback))

    collected = []
    oldest_seen = None

    for item in page_items:
        if not _is_allowed_source_link(item["source"], item["link"]):
            continue
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

        oldest_seen = published_at if oldest_seen is None else min(oldest_seen, published_at)

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
        if not _is_reliable_item(item):
            continue
        collected.append(item)

    append_items(collected)
    if progress_callback:
        progress_callback(
            {
                "stage": "json",
                "collected": len(collected),
                "total": len(news_items),
                "oldest_seen": oldest_seen.strftime("%Y-%m-%d") if oldest_seen else "",
            }
        )

    if (oldest_seen is None or oldest_seen > start_date) and len(news_items) < max_items:
        consecutive_missing_archives = 0
        for page_number in range(1, max_pages + 1):
            archive_url = _build_archive_url(page_number)
            try:
                archive_html = _fetch_url(archive_url)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                logger.warning("Failed to fetch archive page %s: %s", archive_url, exc)
                if isinstance(exc, HTTPError) and exc.code == 404:
                    consecutive_missing_archives += 1
                    if consecutive_missing_archives >= 3:
                        break
                continue
            consecutive_missing_archives = 0

            archive_items = _parse_list_page(archive_html, archive_url)
            if not archive_items:
                if progress_callback:
                    progress_callback(
                        {
                            "stage": "archive_page",
                            "page": page_number,
                            "matched": 0,
                            "added_total": len(news_items),
                            "note": "empty_page",
                        }
                    )
                continue

            page_collected = []
            page_oldest = None
            for item in archive_items:
                if not _is_allowed_source_link(item["source"], item["link"]):
                    continue
                published_at = item["published_at"]
                if not published_at:
                    continue
                page_oldest = published_at if page_oldest is None else min(page_oldest, published_at)

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
                if not _is_reliable_item(item):
                    continue
                page_collected.append(item)

            if progress_callback:
                progress_callback(
                    {
                        "stage": "archive_page",
                        "page": page_number,
                        "matched": len(page_collected),
                        "added_total": len(news_items) + len(page_collected),
                        "oldest_seen": page_oldest.strftime("%Y-%m-%d") if page_oldest else "",
                    }
                )

            if append_items(page_collected):
                break

            if page_oldest and page_oldest < start_date:
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
