"""测试 AI 摘要与题目生成模块（与 app.ai_summary 实现对齐）。"""

import json
from datetime import datetime
from unittest.mock import Mock

import pytest

from app.ai_summary import (
    build_grounded_questions,
    build_grounded_summary,
    generate_questions,
    generate_summary,
)


def _item(
    title: str,
    summary: str,
    published: str,
    published_at: datetime,
) -> dict:
    return {
        "title": title,
        "summary": summary,
        "content": "",
        "published": published,
        "published_at": published_at,
    }


def test_build_grounded_summary_empty():
    out = build_grounded_summary([])
    assert len(out) == 2
    assert "还没有抓取到可用时政内容" in out[0]


def test_build_grounded_summary_with_items():
    items = [
        _item("第二条", "第二条有足够长度的摘要句子用于测试。", "2024-01-16", datetime(2024, 1, 16)),
        _item("第一条", "第一条有足够长度的摘要句子用于测试。", "2024-01-15", datetime(2024, 1, 15)),
    ]
    items.sort(key=lambda x: x["published_at"], reverse=True)
    out = build_grounded_summary(items)
    assert any("共收录 2 条" in line for line in out)


def test_generate_summary_uses_grounded_without_client(monkeypatch):
    monkeypatch.setattr("app.ai_summary._client", lambda: None)
    items = [
        _item("要闻", "热点摘要句子足够长度用于测试逻辑。", "2024-02-01", datetime(2024, 2, 1)),
    ]
    out = generate_summary(items)
    assert isinstance(out, list)
    assert len(out) >= 1


def test_generate_summary_via_openai(monkeypatch):
    mock_client = Mock()
    mock_response = Mock()
    mock_response.output_text = "要点一\n要点二\n"
    mock_client.responses.create.return_value = mock_response
    monkeypatch.setattr("app.ai_summary._client", lambda: mock_client)

    items = [
        _item("标题", "正文摘录需要一定长度才参与摘要。", "2024-01-01", datetime(2024, 1, 1)),
    ]
    out = generate_summary(items)
    assert any("要点" in line for line in out)
    mock_client.responses.create.assert_called_once()


def test_generate_summary_empty_api_response_uses_grounded(monkeypatch):
    mock_client = Mock()
    mock_client.responses.create.return_value = Mock(output_text="")
    monkeypatch.setattr("app.ai_summary._client", lambda: mock_client)

    items = [
        _item("X", "摘要句子够长用于兜底路径测试。" * 2, "2024-04-01", datetime(2024, 4, 1)),
    ]
    out = generate_summary(items)
    assert isinstance(out, list)
    assert len(out) >= 1


def test_build_grounded_questions_too_few_items():
    one = [_item("a", "摘要。" * 5, "2024-01-01", datetime(2024, 1, 1))]
    assert build_grounded_questions(one) == []


def test_build_grounded_questions_four_items():
    items = [
        _item(f"标题{i}", f"摘要{i}内容需要足够长度。" * 3, f"2024-01-{i:02d}", datetime(2024, 1, i))
        for i in range(1, 5)
    ]
    items.sort(key=lambda x: x["published_at"], reverse=True)
    qs = build_grounded_questions(items)
    assert len(qs) >= 3
    assert any(q["type"] == "单选题" for q in qs)


def test_generate_questions_empty():
    assert generate_questions([]) == []


def test_generate_questions_none_is_unsupported():
    with pytest.raises(TypeError):
        generate_questions(None)  # type: ignore[arg-type]


def test_generate_questions_invalid_json_falls_back_to_grounded(monkeypatch):
    mock_client = Mock()
    mock_client.responses.create.return_value = Mock(output_text="not valid json{{{")
    monkeypatch.setattr("app.ai_summary._client", lambda: mock_client)

    items = [
        _item(f"T{i}", "摘要材料需要足够长度。" * 4, f"2024-02-{i:02d}", datetime(2024, 2, i))
        for i in range(1, 5)
    ]
    items.sort(key=lambda x: x["published_at"], reverse=True)
    out = generate_questions(items)
    assert len(out) >= 3
    assert out[0]["type"] in ("单选题", "判断题", "材料概括题", "数据分析题")


def test_generate_questions_valid_json_from_api(monkeypatch):
    payload = [
        {
            "type": "单选题",
            "stem": "题干示例？",
            "options": ["A", "B"],
            "answer": "A",
            "analysis": "解析",
        }
    ]
    mock_client = Mock()
    mock_client.responses.create.return_value = Mock(output_text=json.dumps(payload))
    monkeypatch.setattr("app.ai_summary._client", lambda: mock_client)

    items = [
        _item(f"T{i}", "材料正文摘录。" * 6, f"2024-03-{i:02d}", datetime(2024, 3, i))
        for i in range(1, 5)
    ]
    items.sort(key=lambda x: x["published_at"], reverse=True)
    out = generate_questions(items)
    assert len(out) == 1
    assert out[0]["stem"] == "题干示例？"
    assert out[0]["answer"] == "A"


def test_generate_questions_without_client_returns_grounded(monkeypatch):
    monkeypatch.setattr("app.ai_summary._client", lambda: None)
    items = [
        _item(f"T{i}", "摘要。" * 8, f"2024-05-{i:02d}", datetime(2024, 5, i))
        for i in range(1, 5)
    ]
    items.sort(key=lambda x: x["published_at"], reverse=True)
    out = generate_questions(items)
    assert len(out) >= 3
