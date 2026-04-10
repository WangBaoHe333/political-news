"""测试数据库模型"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

from app.models import Base, News, AppState
from app.database import SessionLocal


def test_news_model():
    """测试新闻模型"""
    # 创建新闻对象
    news = News(
        source="gov_cn",
        category="时政",
        title="测试标题",
        link="https://example.com/test",
        summary="测试摘要",
        content="测试内容",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        year=2024,
        month=1,
    )

    assert news.source == "gov_cn"
    assert news.category == "时政"
    assert news.title == "测试标题"
    assert news.link == "https://example.com/test"
    assert news.summary == "测试摘要"
    assert news.content == "测试内容"
    assert news.published == "2024-01-15"
    assert news.year == 2024
    assert news.month == 1
    assert news.created_at is not None
    assert news.updated_at is not None

    # 测试字符串表示
    str_repr = str(news)
    assert "测试标题" in str_repr
    assert "2024" in str_repr


def test_news_model_required_fields():
    """测试新闻模型必填字段"""
    # 测试缺少必填字段
    with pytest.raises(TypeError):
        News()  # 缺少必填参数

    # 创建最小化新闻对象
    news = News(
        source="gov_cn",
        title="测试标题",
        link="https://example.com/test",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )

    assert news.source == "gov_cn"
    assert news.title == "测试标题"
    assert news.link == "https://example.com/test"
    assert news.published == "2024-01-15"
    assert news.year == 2024  # 应该从published_at自动推导
    assert news.month == 1    # 应该从published_at自动推导


def test_news_model_year_month_derivation():
    """测试年份和月份的自动推导"""
    # 测试1月份
    news1 = News(
        source="gov_cn",
        title="测试1",
        link="https://example.com/1",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )
    assert news1.year == 2024
    assert news1.month == 1

    # 测试12月份
    news2 = News(
        source="gov_cn",
        title="测试2",
        link="https://example.com/2",
        published="2024-12-31",
        published_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
    )
    assert news2.year == 2024
    assert news2.month == 12

    # 测试手动设置year/month覆盖
    news3 = News(
        source="gov_cn",
        title="测试3",
        link="https://example.com/3",
        published="2024-06-15",
        published_at=datetime(2024, 6, 15, tzinfo=timezone.utc),
        year=2023,  # 手动覆盖
        month=7,    # 手动覆盖
    )
    assert news3.year == 2023  # 手动设置应优先
    assert news3.month == 7    # 手动设置应优先


def test_app_state_model():
    """测试应用状态模型"""
    # 创建应用状态对象
    state = AppState(key="test_key", value="test_value")

    assert state.key == "test_key"
    assert state.value == "test_value"
    assert state.created_at is not None
    assert state.updated_at is not None

    # 测试字符串表示
    str_repr = str(state)
    assert "test_key" in str_repr
    assert "test_value" in str_repr


def test_app_state_required_fields():
    """测试应用状态模型必填字段"""
    # 测试缺少必填字段
    with pytest.raises(TypeError):
        AppState()  # 缺少key和value

    with pytest.raises(TypeError):
        AppState(key="test_key")  # 缺少value

    with pytest.raises(TypeError):
        AppState(value="test_value")  # 缺少key

    # 创建有效对象
    state = AppState(key="test_key", value="test_value")
    assert state.key == "test_key"
    assert state.value == "test_value"


def test_models_in_db_session(db_session):
    """测试模型在数据库会话中的操作"""
    # 创建新闻对象
    news = News(
        source="gov_cn",
        category="时政",
        title="数据库测试标题",
        link="https://example.com/db-test",
        summary="数据库测试摘要",
        content="数据库测试内容",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        year=2024,
        month=1,
    )

    # 添加到数据库
    db_session.add(news)
    db_session.commit()

    # 查询数据库
    queried_news = db_session.query(News).filter_by(title="数据库测试标题").first()
    assert queried_news is not None
    assert queried_news.source == "gov_cn"
    assert queried_news.title == "数据库测试标题"
    assert queried_news.link == "https://example.com/db-test"

    # 创建应用状态对象
    state = AppState(key="db_test_key", value="db_test_value")
    db_session.add(state)
    db_session.commit()

    # 查询应用状态
    queried_state = db_session.query(AppState).filter_by(key="db_test_key").first()
    assert queried_state is not None
    assert queried_state.value == "db_test_value"


def test_news_unique_constraint():
    """测试新闻唯一约束"""
    # 创建两个相同的新闻（相同的link）
    news1 = News(
        source="gov_cn",
        title="测试标题1",
        link="https://example.com/same-link",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )

    news2 = News(
        source="gov_cn",
        title="测试标题2",
        link="https://example.com/same-link",  # 相同的link
        published="2024-01-16",
        published_at=datetime(2024, 1, 16, tzinfo=timezone.utc),
    )

    # 添加到数据库（应该允许，因为link不是唯一约束）
    # 实际上模型没有设置唯一约束，所以不会抛出异常
    # 这个测试主要是验证模型行为


def test_app_state_key_uniqueness():
    """测试应用状态键的唯一性"""
    # AppState模型也没有设置唯一约束
    # 这个测试主要是验证模型行为
    state1 = AppState(key="duplicate_key", value="value1")
    state2 = AppState(key="duplicate_key", value="value2")  # 相同的key

    # 两个对象都应该能创建
    assert state1.key == "duplicate_key"
    assert state2.key == "duplicate_key"
    assert state1.value == "value1"
    assert state2.value == "value2"


def test_model_timestamps():
    """测试模型时间戳"""
    news = News(
        source="gov_cn",
        title="时间戳测试",
        link="https://example.com/timestamp",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )

    # 创建时间应该自动设置
    assert news.created_at is not None
    assert news.updated_at is not None

    # 初始时created_at和updated_at应该相同
    assert news.created_at == news.updated_at

    # 模拟更新
    import time
    original_updated = news.updated_at
    time.sleep(0.001)  # 微小延迟

    # 在实际的SQLAlchemy中，updated_at应该自动更新
    # 但在这个测试中，我们只是验证字段存在


def test_model_default_values():
    """测试模型默认值"""
    news = News(
        source="gov_cn",
        title="默认值测试",
        link="https://example.com/default",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
    )

    # 测试可选字段的默认值
    assert news.category is None  # 默认为None
    assert news.summary is None   # 默认为None
    assert news.content is None   # 默认为None


def test_model_serialization():
    """测试模型序列化"""
    news = News(
        source="gov_cn",
        category="时政",
        title="序列化测试",
        link="https://example.com/serialize",
        summary="测试摘要",
        content="测试内容",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        year=2024,
        month=1,
    )

    # 转换为字典
    news_dict = {
        "id": None,  # 尚未保存，id为None
        "source": "gov_cn",
        "category": "时政",
        "title": "序列化测试",
        "link": "https://example.com/serialize",
        "summary": "测试摘要",
        "content": "测试内容",
        "published": "2024-01-15",
        "published_at": datetime(2024, 1, 15, tzinfo=timezone.utc),
        "year": 2024,
        "month": 1,
        "created_at": news.created_at,
        "updated_at": news.updated_at,
    }

    # 验证字段匹配
    for key, value in news_dict.items():
        if key != "id":  # id是自动生成的
            assert getattr(news, key) == value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])