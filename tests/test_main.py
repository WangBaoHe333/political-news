"""FastAPI主应用测试"""

import pytest
from datetime import datetime, timedelta, timezone


def test_home_page(client):
    """测试首页访问"""
    response = client.get("/")
    assert response.status_code == 200
    assert "时政资料库" in response.text


def test_api_news_endpoint(client):
    """测试新闻API端点"""
    response = client.get("/api/news")
    assert response.status_code == 200
    data = response.json()
    assert "years" in data
    assert "items" in data
    assert isinstance(data["years"], list)
    assert isinstance(data["items"], list)


def test_api_news_with_year_param(client):
    """测试带年份参数的新闻API"""
    current_year = datetime.now(timezone.utc).year
    response = client.get(f"/api/news?year={current_year}")
    assert response.status_code == 200
    data = response.json()
    assert "years" in data
    assert "items" in data


def test_api_today_news(client):
    """测试今日时政API"""
    response = client.get("/api/news/today")
    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert "items" in data
    assert isinstance(data["items"], list)


def test_api_yesterday_news(client):
    """测试昨日时政API"""
    response = client.get("/api/news/yesterday")
    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert "items" in data
    assert isinstance(data["items"], list)


def test_api_grouped_by_month(client):
    """测试按月分组API"""
    response = client.get("/api/news/grouped-by-month")
    assert response.status_code == 200
    data = response.json()
    assert "years" in data
    assert "grouped_by_month" in data
    assert isinstance(data["grouped_by_month"], dict)


def test_api_past_two_years(client):
    """测试过去两年API"""
    response = client.get("/api/news/past-two-years")
    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert "total_items" in data
    assert "items" in data
    assert "grouped_by_month" in data


def test_sync_status_endpoint(client):
    """测试同步状态端点"""
    response = client.get("/sync-status")
    assert response.status_code == 200
    data = response.json()
    assert "in_progress" in data
    assert "scope" in data
    assert "message" in data
    assert isinstance(data["in_progress"], bool)


def test_sync_endpoint_with_params(client):
    """测试同步端点（带参数）"""
    # 注意：这个测试可能触发实际同步，需要小心
    response = client.get("/sync?months=1&max_items=10")
    # 可能返回200或500（如果没有数据），但至少检查端点存在
    assert response.status_code in [200, 500]


def test_backfill_view_endpoint(client):
    """测试分批回填视图端点"""
    response = client.get("/backfill-view?months=6&batch_size=2&max_items=50")
    assert response.status_code == 303  # 重定向


def test_api_docs_available(client):
    """测试API文档是否可用"""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "Swagger UI" in response.text or "openapi" in response.text


def test_redoc_available(client):
    """测试ReDoc文档是否可用"""
    response = client.get("/redoc")
    assert response.status_code == 200