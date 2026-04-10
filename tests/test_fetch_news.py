"""测试新闻抓取模块"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
import feedparser

from app.fetch_news import (
    fetch_news,
    parse_news_item,
    fetch_json_news,
    fetch_archive_news,
    _fetch_page,
    _parse_date,
)


def test_parse_date():
    """测试日期解析"""
    # 测试各种日期格式
    assert _parse_date("2024-01-15") == datetime(2024, 1, 15)
    assert _parse_date("2024年01月15日") == datetime(2024, 1, 15)
    assert _parse_date("2024/01/15") == datetime(2024, 1, 15)
    assert _parse_date("15 Jan 2024") == datetime(2024, 1, 15)

    # 测试无效日期
    assert _parse_date("无效日期") is None
    assert _parse_date("") is None


def test_parse_news_item():
    """测试新闻条目解析"""
    # 正常条目
    item = {
        "title": "测试标题",
        "link": "https://example.com/test",
        "published": "2024-01-15",
        "summary": "测试摘要",
    }

    parsed = parse_news_item(item)
    assert parsed["title"] == "测试标题"
    assert parsed["link"] == "https://example.com/test"
    assert parsed["published"] == "2024-01-15"
    assert parsed["summary"] == "测试摘要"
    assert parsed["year"] == 2024
    assert parsed["month"] == 1

    # 缺少字段的条目
    incomplete_item = {"title": "标题"}
    parsed = parse_news_item(incomplete_item)
    assert parsed["title"] == "标题"
    assert parsed["link"] == ""
    assert parsed["published"] == ""
    assert parsed["summary"] == ""


@patch("app.fetch_news.requests.get")
def test_fetch_page_success(mock_get):
    """测试成功获取页面"""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "<html>测试内容</html>"
    mock_get.return_value = mock_response

    content = _fetch_page("https://example.com")
    assert content == "<html>测试内容</html>"
    mock_get.assert_called_once_with("https://example.com", timeout=30)


@patch("app.fetch_news.requests.get")
def test_fetch_page_failure(mock_get):
    """测试获取页面失败"""
    mock_response = Mock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    content = _fetch_page("https://example.com")
    assert content == ""
    mock_get.assert_called_once_with("https://example.com", timeout=30)


@patch("app.fetch_news._fetch_page")
@patch("app.fetch_news.feedparser.parse")
def test_fetch_json_news(mock_parse, mock_fetch):
    """测试JSON新闻获取"""
    # 模拟RSS响应
    mock_feed = Mock()
    mock_feed.entries = [
        {
            "title": "新闻1",
            "link": "https://example.com/1",
            "published": "2024-01-15",
            "summary": "摘要1",
        },
        {
            "title": "新闻2",
            "link": "https://example.com/2",
            "published": "2024-01-16",
            "summary": "摘要2",
        },
    ]
    mock_parse.return_value = mock_feed
    mock_fetch.return_value = "<rss>data</rss>"

    items = fetch_json_news()
    assert len(items) == 2
    assert items[0]["title"] == "新闻1"
    assert items[1]["title"] == "新闻2"


@patch("app.fetch_news._fetch_page")
def test_fetch_archive_news(mock_fetch):
    """测试归档新闻获取"""
    # 模拟HTML响应
    mock_html = """
    <html>
    <div class="news_list">
        <li>
            <a href="/test1">标题1</a>
            <span class="date">2024-01-15</span>
        </li>
        <li>
            <a href="/test2">标题2</a>
            <span class="date">2024-01-16</span>
        </li>
    </div>
    </html>
    """
    mock_fetch.return_value = mock_html

    items = fetch_archive_news(1, datetime(2024, 1, 1), datetime(2024, 1, 31))
    assert len(items) == 2
    assert items[0]["title"] == "标题1"
    assert items[0]["link"] == "https://www.gov.cn/test1"
    assert items[1]["title"] == "标题2"


@patch("app.fetch_news.fetch_json_news")
@patch("app.fetch_news.fetch_archive_news")
def test_fetch_news_with_filters(mock_archive, mock_json):
    """测试带过滤条件的新闻抓取"""
    # 模拟返回数据
    mock_json.return_value = [
        {"title": "新闻1", "published": "2024-01-15", "year": 2024, "month": 1},
        {"title": "新闻2", "published": "2024-02-15", "year": 2024, "month": 2},
    ]

    mock_archive.return_value = [
        {"title": "归档1", "published": "2023-12-15", "year": 2023, "month": 12},
    ]

    # 测试年份过滤
    items = fetch_news(year=2024)
    assert len(items) == 2

    # 测试日期范围过滤
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 31)
    items = fetch_news(start_date=start_date, end_date=end_date)
    # 应该只包含1月份的新闻
    assert len([i for i in items if i["month"] == 1]) >= 1


def test_fetch_news_progress_callback():
    """测试进度回调"""
    progress_data = []

    def progress_callback(info):
        progress_data.append(info)

    with patch("app.fetch_news.fetch_json_news", return_value=[]), \
         patch("app.fetch_news.fetch_archive_news", return_value=[]):

        fetch_news(months=1, progress_callback=progress_callback)

        # 应该至少调用一次进度回调
        assert len(progress_data) > 0
        assert "stage" in progress_data[0]


@patch("app.fetch_news._fetch_page")
def test_fetch_news_empty_response(mock_fetch):
    """测试空响应处理"""
    mock_fetch.return_value = ""

    items = fetch_news(months=1, max_items=10)
    assert len(items) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])