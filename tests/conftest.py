import pytest
import os
import sys
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.models import Base


@pytest.fixture(scope="session")
def test_db():
    """创建测试数据库（会话结束时释放引擎，避免未关闭连接告警）。"""
    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    yield TestingSessionLocal
    test_engine.dispose()


@pytest.fixture
def db_session(test_db):
    """提供数据库会话"""
    session = test_db()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """提供测试客户端"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """模拟环境变量"""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("OPENAI_API_KEY", "test_key")
    monkeypatch.setenv("AUTO_SYNC_ON_STARTUP", "0")