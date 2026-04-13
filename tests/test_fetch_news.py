"""测试新闻抓取模块（与 app.fetch_news 实现对齐）。"""

from datetime import datetime
from urllib.error import URLError
from unittest.mock import patch

import pytest

from app.fetch_news import (
    _extract_date_from_url,
    _extract_date,
    _fetch_url,
    _is_allowed_source_link,
    _iter_month_list_pages,
    _load_external_html_sources,
    _load_external_source_feeds,
    _people_archive_urls,
    _classify_category,
    _normalize_text,
    _target_range,
    fetch_news,
)


def test_normalize_text():
    assert _normalize_text("  a  \n  b  ") == "a b"
    assert _normalize_text("") == ""


def test_extract_date_iso_and_slash():
    assert _extract_date("2024-01-15") == datetime(2024, 1, 15)
    assert _extract_date("2024/01/15") == datetime(2024, 1, 15)


def test_extract_date_chinese():
    assert _extract_date("2024年01月15日") == datetime(2024, 1, 15)


def test_extract_date_english_month():
    assert _extract_date("15 Jan 2024") == datetime(2024, 1, 15)


def test_extract_date_invalid_or_empty():
    assert _extract_date("") is None
    assert _extract_date("无效日期无年份") is None


def test_extract_date_from_url():
    assert _extract_date_from_url("https://politics.people.com.cn/n1/2025/0108/c1024-40412345.html") == datetime(2025, 1, 8)
    assert _extract_date_from_url("https://www.news.cn/politics/2026-04/13/c_112233.htm") == datetime(2026, 4, 13)
    assert _extract_date_from_url("https://example.com/no-date") is None


def test_allowed_source_link_uses_whitelist():
    assert _is_allowed_source_link("gov_cn", "https://www.gov.cn/yaowen/test.htm")
    assert _is_allowed_source_link("xinhuanet", "https://www.news.cn/politics/test.htm")
    assert _is_allowed_source_link("cctv", "https://news.cctv.com/2026/04/11/ARTItest.shtml")
    assert _is_allowed_source_link("mfa", "https://www.mfa.gov.cn/web/ttxw/test.shtml")
    assert not _is_allowed_source_link("gov_cn", "https://fake.example.com/test.htm")
    assert not _is_allowed_source_link("sina", "https://news.sina.com.cn/test.htm")


def test_classify_category_prefers_editorial_buckets():
    assert _classify_category("mfa", "时政", "外交部发布重要消息") == "外交"
    assert _classify_category("gov_cn", "要闻", "受权发布丨政府工作报告全文") == "权威发布"
    assert _classify_category("people_cn", "时政", "国务院任免国家工作人员") == "人事"


def test_target_range_year():
    start, end = _target_range(year=2024)
    assert start == datetime(2024, 1, 1)
    assert end.year == 2024 and end.month == 12


def test_target_range_explicit_dates():
    a = datetime(2024, 6, 1)
    b = datetime(2024, 6, 30, 23, 59, 59)
    start, end = _target_range(start_date=a, end_date=b)
    assert start == a and end == b


def test_iter_month_list_pages_builds_month_directories():
    start = datetime(2025, 1, 1)
    end = datetime(2025, 3, 31, 23, 59, 59)
    urls = _iter_month_list_pages(start, end, max_index_pages=2)
    assert "https://www.gov.cn/yaowen/liebiao/202503/index.htm" in urls
    assert "https://www.gov.cn/yaowen/liebiao/202503/index_2.htm" in urls
    assert "https://www.gov.cn/yaowen/liebiao/202501/index.htm" in urls


def test_people_archive_urls_build_expected_pages():
    urls = _people_archive_urls(5)
    assert urls[0] == "https://politics.people.com.cn/GB/1024/index.html"
    assert "https://politics.people.com.cn/GB/1024/index2.html" in urls
    assert "https://politics.people.com.cn/GB/1024/index5.html" in urls


@patch("app.fetch_news._fetch_url")
@patch("app.fetch_news._load_json_feed")
def test_fetch_news_respects_range_and_article_fetch(mock_load, mock_fetch):
    """JSON 列表与详情页均由 mock 提供，不访问外网。"""
    article_html = """<html><body><div class="pages_content">
    <p>这是一段足够长的正文内容用于摘要提取与单元测试。</p>
    </div></body></html>"""

    def fetch_side_effect(url: str) -> str:
        if "home_" in url:
            return "<html><body></body></html>"
        return article_html

    mock_fetch.side_effect = fetch_side_effect
    mock_load.return_value = [
        {
            "source": "gov_cn",
            "category": "时政",
            "title": "测试时政标题",
            "link": "https://www.gov.cn/yaowen/content_test.htm",
            "published": "2024-06-15",
            "published_at": datetime(2024, 6, 15),
            "summary": "",
            "content": "",
        }
    ]

    start = datetime(2024, 6, 1)
    end = datetime(2024, 6, 30, 23, 59, 59)
    items = fetch_news(start_date=start, end_date=end, max_items=10, max_pages=1)

    assert len(items) == 1
    assert items[0]["title"] == "测试时政标题"
    assert "正文" in (items[0].get("summary") or "")
    assert items[0]["published_at"].year == 2024


@patch("app.fetch_news._fetch_url")
@patch("app.fetch_news._load_json_feed")
def test_fetch_news_empty_feed(mock_load, mock_fetch):
    mock_load.return_value = []
    mock_fetch.return_value = "<html></html>"
    items = fetch_news(months=1, max_items=10, max_pages=1)
    assert items == []


@patch("app.fetch_news._fetch_url")
@patch("app.fetch_news._load_json_feed")
def test_fetch_news_progress_callback(mock_load, mock_fetch):
    mock_load.return_value = []
    mock_fetch.return_value = ""

    progress: list = []

    def cb(info):
        progress.append(info)

    fetch_news(months=1, max_items=5, max_pages=1, progress_callback=cb)
    assert len(progress) >= 1
    assert all("stage" in p for p in progress)


@patch("app.fetch_news._fetch_url")
@patch("app.fetch_news._load_json_feed")
def test_fetch_news_discards_untrusted_domain(mock_load, mock_fetch):
    article_html = """<html><body><div class="pages_content">
    <p>这是一段足够长的正文内容用于摘要提取与单元测试。</p>
    </div></body></html>"""

    mock_fetch.return_value = article_html
    mock_load.return_value = [
        {
            "source": "gov_cn",
            "category": "时政",
            "title": "异常来源测试",
            "link": "https://example.com/not-official.htm",
            "published": "2024-06-15",
            "published_at": datetime(2024, 6, 15),
            "summary": "",
            "content": "",
        }
    ]

    items = fetch_news(start_date=datetime(2024, 6, 1), end_date=datetime(2024, 6, 30, 23, 59, 59), max_items=10, max_pages=1)
    assert items == []


@patch("app.fetch_news._fetch_url")
@patch("app.fetch_news._load_json_feed")
def test_fetch_news_uses_url_date_fallback(mock_load, mock_fetch):
    mock_load.return_value = [
        {
            "source": "people_cn",
            "category": "时政",
            "title": "带日期链接的测试文章",
            "link": "https://politics.people.com.cn/n1/2025/0108/c1024-40412345.html",
            "published": "",
            "published_at": None,
            "summary": "",
            "content": "",
        }
    ]
    mock_fetch.return_value = "<html><body><p>这是一段足够长的测试正文内容，用于验证链接日期兜底逻辑能够生效。</p></body></html>"

    items = fetch_news(
        start_date=datetime(2025, 1, 1),
        end_date=datetime(2025, 1, 31, 23, 59, 59),
        max_items=10,
        max_pages=1,
    )

    assert len(items) == 1
    assert items[0]["published_at"] == datetime(2025, 1, 8)


def test_fetch_url_retries_then_succeeds(monkeypatch):
    calls = {"count": 0}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"ok"

    def fake_urlopen(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise URLError("temporary failure")
        return _Response()

    monkeypatch.setattr("app.fetch_news.urlopen", fake_urlopen)
    monkeypatch.setattr("app.fetch_news.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("app.fetch_news.HTTP_RETRIES", 1)
    assert _fetch_url("https://www.gov.cn/test") == "ok"
    assert calls["count"] == 2


def test_source_health_callback_for_empty_rss(monkeypatch):
    monkeypatch.setattr(
        "app.fetch_news.CURATED_RSS_SOURCES",
        [
            {
                "source": "people_cn",
                "category": "时政",
                "feed_url": "https://example.com/rss.xml",
                "base_url": "https://www.people.com.cn/",
                "max_entries": 5,
            }
        ],
    )
    monkeypatch.setattr("app.fetch_news._fetch_url", lambda _url: "<rss></rss>")
    monkeypatch.setattr("app.fetch_news._parse_feed_entries", lambda _cfg, _xml: [])

    events = []
    _load_external_source_feeds(progress_callback=lambda info: events.append(info))
    source_health = [event for event in events if event.get("stage") == "source_health"]

    assert len(source_health) == 1
    assert source_health[0]["status"] == "empty"
    assert source_health[0]["source"] == "people_cn"


def test_source_health_callback_for_html_error(monkeypatch):
    monkeypatch.setattr(
        "app.fetch_news.CURATED_HTML_SOURCES",
        [
            {
                "source": "mfa",
                "category": "外交",
                "list_urls": ["https://example.com/list"],
                "base_url": "https://www.mfa.gov.cn/",
                "link_keywords": (),
                "article_patterns": (".shtml",),
                "max_entries": 10,
            }
        ],
    )
    monkeypatch.setattr("app.fetch_news._fetch_url", lambda _url: (_ for _ in ()).throw(URLError("down")))

    events = []
    _load_external_html_sources(progress_callback=lambda info: events.append(info))
    source_health = [event for event in events if event.get("stage") == "source_health"]

    assert len(source_health) == 1
    assert source_health[0]["status"] == "error"
    assert source_health[0]["source"] == "mfa"


def test_source_health_callback_for_rss_error(monkeypatch):
    monkeypatch.setattr(
        "app.fetch_news.CURATED_RSS_SOURCES",
        [
            {
                "source": "xinhuanet",
                "category": "时政",
                "feed_url": "https://example.com/rss.xml",
                "base_url": "https://www.news.cn/",
                "max_entries": 5,
            }
        ],
    )
    monkeypatch.setattr("app.fetch_news._fetch_url", lambda _url: (_ for _ in ()).throw(URLError("network down")))

    events = []
    _load_external_source_feeds(progress_callback=lambda info: events.append(info))
    source_health = [event for event in events if event.get("stage") == "source_health"]

    assert len(source_health) == 1
    assert source_health[0]["status"] == "error"
    assert source_health[0]["source"] == "xinhuanet"
