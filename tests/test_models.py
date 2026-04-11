"""测试数据库模型（与 app.models 实现对齐）。"""

import pytest
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.models import AppState, Base, News


def test_news_model():
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
    assert hasattr(news, "published_at")


def test_news_model_defaults_after_flush(db_session):
    """INSERT 时由数据库 / ORM 写入 Column 默认值。"""
    news = News(
        title="仅标题",
        link="https://example.com/minimal",
        published="2024-06-01",
        published_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        year=2024,
        month=6,
    )
    db_session.add(news)
    db_session.flush()
    assert news.source == "gov_cn"
    assert news.category == "时政"
    assert news.summary == ""
    assert news.content == ""


def test_news_model_year_month_explicit():
    """year / month 由业务层写入，模型不自动推导。"""
    news = News(
        title="测试1",
        link="https://example.com/1",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        year=2024,
        month=1,
    )
    assert news.year == 2024
    assert news.month == 1

    news2 = News(
        title="测试2",
        link="https://example.com/2",
        published="2024-12-31",
        published_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
        year=2024,
        month=12,
    )
    assert news2.month == 12


def test_app_state_model():
    state = AppState(key="test_key", value="test_value")
    assert state.key == "test_key"
    assert state.value == "test_value"


def test_models_in_db_session(db_session):
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

    db_session.add(news)
    db_session.commit()

    queried_news = db_session.query(News).filter_by(title="数据库测试标题").first()
    assert queried_news is not None
    assert queried_news.source == "gov_cn"
    assert queried_news.title == "数据库测试标题"
    assert queried_news.link == "https://example.com/db-test"

    state = AppState(key="db_test_key", value="db_test_value")
    db_session.add(state)
    db_session.commit()

    queried_state = db_session.query(AppState).filter_by(key="db_test_key").first()
    assert queried_state is not None
    assert queried_state.value == "db_test_value"


def test_news_link_unique_in_db(db_session):
    n1 = News(
        title="A",
        link="https://example.com/same",
        published="2024-01-15",
        published_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
        year=2024,
        month=1,
    )
    n2 = News(
        title="B",
        link="https://example.com/same",
        published="2024-01-16",
        published_at=datetime(2024, 1, 16, tzinfo=timezone.utc),
        year=2024,
        month=1,
    )
    db_session.add(n1)
    db_session.commit()
    db_session.add(n2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_app_state_primary_key_unique_in_db(db_session):
    db_session.add(AppState(key="dup", value="v1"))
    db_session.commit()
    db_session.add(AppState(key="dup", value="v2"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_model_serialization_fields():
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
    expected = {
        "source": "gov_cn",
        "category": "时政",
        "title": "序列化测试",
        "link": "https://example.com/serialize",
        "summary": "测试摘要",
        "content": "测试内容",
        "published": "2024-01-15",
        "published_at": news.published_at,
        "year": 2024,
        "month": 1,
    }
    for key, value in expected.items():
        assert getattr(news, key) == value
