"""测试新闻抓取模块（与 app.fetch_news 实现对齐）。"""

from datetime import datetime
from unittest.mock import patch

import pytest

from app.fetch_news import (
    _extract_date,
    _is_allowed_source_link,
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
