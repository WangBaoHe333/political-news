"""FastAPI主应用测试"""

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_home_page(client):
    """测试首页访问"""
    response = client.get("/")
    assert response.status_code == 200
    assert "今日时政" in response.text
    assert "分类专题" in response.text
    assert "权威来源" in response.text
    assert "同步状态" in response.text
    assert "只显示数据库里日期为今天的内容" in response.text


def test_latest_page_alias(client):
    """测试最新时政别名页面"""
    response = client.get("/latest")
    assert response.status_code == 200
    assert "全部时政" in response.text
    assert "完整浏览列表" in response.text


def test_archive_page(client):
    """测试按月归档页面"""
    response = client.get("/archive?page=1")
    assert response.status_code == 200
    assert "按月归档" in response.text
    assert "默认折叠显示" in response.text


def test_categories_and_sources_pages(client):
    """测试分类页和数据源页"""
    categories_response = client.get("/categories")
    assert categories_response.status_code == 200
    assert "分类专题" in categories_response.text

    sources_response = client.get("/sources")
    assert sources_response.status_code == 200
    assert "数据源" in sources_response.text
    assert "来源覆盖" in sources_response.text


def test_search_page_with_filters_and_pagination(client):
    """测试搜索页带筛选和分页参数"""
    response = client.get("/search?q=%E6%B5%8B%E8%AF%95&year=2025&source=people_cn&page=1")
    assert response.status_code == 200
    assert "搜索结果" in response.text
    assert "搜索" in response.text
    assert "人民网" in response.text


def test_search_page_supports_year_only_filter(client):
    """测试只选择年份也能返回搜索结果页"""
    response = client.get("/search?year=2025")
    assert response.status_code == 200
    assert "当前默认在 2025 年范围内搜索标题、摘要、正文、来源和发布日期。" in response.text


def test_search_defaults_to_current_year(client):
    """测试搜索框默认选中当前年份"""
    current_year = datetime.now(timezone.utc).year
    response = client.get("/")
    assert response.status_code == 200
    assert f"<option value='{current_year}' selected>" in response.text


def test_year_pages(client):
    """测试年份入口和年份详情页面"""
    response = client.get("/years")
    assert response.status_code == 200
    assert "按年份浏览" in response.text
    assert "2025" in response.text

    detail_response = client.get("/year/2025?page=1")
    assert detail_response.status_code == 200
    assert "2025 年时政" in detail_response.text


def test_category_detail_page(client):
    """测试分类详情页"""
    response = client.get("/category/shizheng?page=1")
    assert response.status_code == 200
    assert "时政专题" in response.text


def test_today_and_yesterday_pages(client):
    """测试今日和昨日独立页面"""
    today_response = client.get("/today")
    assert today_response.status_code == 200
    assert "今日时政" in today_response.text

    yesterday_response = client.get("/yesterday")
    assert yesterday_response.status_code == 200
    assert "昨日时政" in yesterday_response.text


def test_status_page(client):
    """测试同步状态页面"""
    response = client.get("/status")
    assert response.status_code == 200
    assert "同步状态" in response.text
    assert "同步近两年到数据库" in response.text
    assert "来源覆盖" in response.text


def test_news_detail_page(client, monkeypatch):
    """测试站内详情页"""
    from app.routers import web

    fake_item = SimpleNamespace(
        id=1,
        title="测试时政标题",
        link="https://example.com/article",
        source="people_cn",
        summary="测试摘要",
        content="第一段内容\n第二段内容",
        published="2026-04-11",
        published_at=datetime(2026, 4, 11, tzinfo=timezone.utc),
        year=2026,
        month=4,
    )

    monkeypatch.setattr(web, "get_news_by_id", lambda news_id: fake_item if news_id == 1 else None)
    monkeypatch.setattr(web, "query_news", lambda **kwargs: ([fake_item], [2026, 2025]))
    monkeypatch.setattr(web, "get_year_counts", lambda min_year=None: {2026: 1, 2025: 0})

    response = client.get("/news/1")
    assert response.status_code == 200
    assert "站内详情" in response.text
    assert "测试时政标题" in response.text
    assert "人民网" in response.text


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
    assert "query" in data


def test_api_news_search_param(client):
    """测试新闻搜索参数"""
    response = client.get("/api/news?q=%E6%B5%8B%E8%AF%95")
    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert isinstance(data["items"], list)


def test_api_news_supports_category_param(client):
    """测试新闻 API 支持分类参数"""
    response = client.get("/api/news?category=%E6%97%B6%E6%94%BF")
    assert response.status_code == 200
    data = response.json()
    assert "category" in data


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


def test_health_endpoint(client):
    """健康检查"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "healthy"
    assert "timestamp" in data


def test_sync_status_endpoint(client):
    """测试同步状态端点"""
    response = client.get("/sync-status")
    assert response.status_code == 200
    data = response.json()
    assert "in_progress" in data
    assert "scope" in data
    assert "message" in data
    assert "last_sync_at" in data
    assert isinstance(data["in_progress"], bool)


def test_sync_endpoint_with_params(client, monkeypatch):
    """测试同步端点（带参数），不发起外网抓取。"""
    from app.routers import sync_routes

    def fake_fetch(**kwargs):
        return {"fetched": 0, "saved": 0}

    monkeypatch.setattr(sync_routes, "fetch_and_save_news", fake_fetch)
    response = client.get("/sync?months=1&max_items=10")
    assert response.status_code == 200
    assert response.json() == {"fetched": 0, "saved": 0}


def test_backfill_view_endpoint(client):
    """测试分批回填视图端点"""
    response = client.get(
        "/backfill-view?months=6&batch_size=2&max_items=50",
        follow_redirects=False,
    )
    assert response.status_code == 303  # 重定向
    assert response.headers["location"].startswith("/status?sync_status=")


def test_sync_view_redirects_to_status(client, monkeypatch):
    """测试同步视图跳转到独立状态页"""
    from app.routers import sync_routes

    monkeypatch.setattr(sync_routes, "start_background_sync", lambda *args, **kwargs: True)
    response = client.get("/sync-view?months=24", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/status?sync_status=")


def test_sync_view_requires_token_when_configured(client, monkeypatch):
    """测试生产环境可为同步入口启用令牌保护"""
    monkeypatch.setenv("SYNC_ADMIN_TOKEN", "secret-token")
    response = client.get("/sync-view?months=24", follow_redirects=False)
    assert response.status_code == 403


def test_api_docs_available(client):
    """测试API文档是否可用"""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "Swagger UI" in response.text or "openapi" in response.text


def test_redoc_available(client):
    """测试ReDoc文档是否可用"""
    response = client.get("/redoc")
    assert response.status_code == 200


def test_api_docs_can_be_hidden_in_production(monkeypatch):
    """生产环境可关闭文档入口"""
    from app.main import create_app

    monkeypatch.setenv("EXPOSE_API_DOCS", "0")
    hidden_docs_app = create_app()

    with TestClient(hidden_docs_app) as hidden_client:
        assert hidden_client.get("/docs").status_code == 404
        assert hidden_client.get("/redoc").status_code == 404
        assert hidden_client.get("/openapi.json").status_code == 404
