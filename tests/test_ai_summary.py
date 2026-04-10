"""测试AI摘要和题目生成模块"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import openai

from app.ai_summary import (
    generate_summary,
    generate_questions,
    _call_openai_api,
    SUMMARY_PROMPT_TEMPLATE,
    QUESTION_PROMPT_TEMPLATE,
)


def test_call_openai_api_success():
    """测试成功调用OpenAI API"""
    mock_response = Mock()
    mock_choice = Mock()
    mock_choice.message.content = "测试响应"
    mock_response.choices = [mock_choice]
    mock_response.usage = Mock(total_tokens=10)

    with patch("app.ai_summary.openai.chat.completions.create", return_value=mock_response):
        result = _call_openai_api("测试提示", "gpt-4o-mini")
        assert result == "测试响应"


def test_call_openai_api_failure():
    """测试OpenAI API调用失败"""
    with patch("app.ai_summary.openai.chat.completions.create", side_effect=Exception("API错误")):
        result = _call_openai_api("测试提示", "gpt-4o-mini")
        assert result == ""


def test_call_openai_api_no_api_key():
    """测试没有API密钥的情况"""
    with patch("app.ai_summary.os.getenv", return_value=""):
        result = _call_openai_api("测试提示", "gpt-4o-mini")
        assert result == ""


def test_generate_summary_basic():
    """测试基础摘要生成"""
    news_items = [
        {
            "title": "新闻标题1",
            "summary": "新闻摘要1",
            "published": "2024-01-15",
            "source": "gov_cn",
        },
        {
            "title": "新闻标题2",
            "summary": "新闻摘要2",
            "published": "2024-01-16",
            "source": "gov_cn",
        },
    ]

    with patch("app.ai_summary._call_openai_api", return_value="1. 要点1\n2. 要点2\n3. 要点3"):
        summary = generate_summary(news_items)
        assert isinstance(summary, list)
        assert len(summary) == 3
        assert "要点1" in summary[0]
        assert "要点2" in summary[1]
        assert "要点3" in summary[2]


def test_generate_summary_empty_input():
    """测试空输入"""
    summary = generate_summary([])
    assert summary == ["当前无时政数据"]

    summary = generate_summary(None)
    assert summary == ["当前无时政数据"]


def test_generate_summary_api_error():
    """测试API错误时的降级处理"""
    news_items = [{"title": "测试新闻", "summary": "测试摘要"}]

    with patch("app.ai_summary._call_openai_api", return_value=""):
        summary = generate_summary(news_items)
        # 应该返回降级摘要
        assert len(summary) > 0
        assert "基于当前" in summary[0]


def test_generate_questions_basic():
    """测试基础题目生成"""
    news_items = [
        {
            "title": "经济工作会议召开",
            "summary": "中央经济工作会议强调高质量发展",
            "published": "2024-01-15",
            "source": "gov_cn",
        }
    ]

    mock_response = """[
        {
            "type": "单选题",
            "stem": "2024年中央经济工作会议强调的重点是什么？",
            "options": ["A. 高速增长", "B. 高质量发展", "C. 扩大投资", "D. 刺激消费"],
            "answer": "B",
            "analysis": "会议明确指出要坚持高质量发展..."
        }
    ]"""

    with patch("app.ai_summary._call_openai_api", return_value=mock_response):
        questions = generate_questions(news_items)
        assert isinstance(questions, list)
        assert len(questions) == 1
        assert questions[0]["type"] == "单选题"
        assert questions[0]["stem"] == "2024年中央经济工作会议强调的重点是什么？"
        assert "B. 高质量发展" in questions[0]["options"]
        assert questions[0]["answer"] == "B"
        assert "高质量发展" in questions[0]["analysis"]


def test_generate_questions_invalid_json():
    """测试无效JSON响应"""
    news_items = [{"title": "测试", "summary": "测试"}]

    # 测试无效JSON
    with patch("app.ai_summary._call_openai_api", return_value="无效JSON"):
        questions = generate_questions(news_items)
        assert len(questions) == 0

    # 测试空响应
    with patch("app.ai_summary._call_openai_api", return_value=""):
        questions = generate_questions(news_items)
        assert len(questions) == 0


def test_generate_questions_empty_input():
    """测试空输入"""
    questions = generate_questions([])
    assert questions == []

    questions = generate_questions(None)
    assert questions == []


def test_generate_questions_fallback():
    """测试降级题目生成"""
    news_items = [{"title": "测试", "summary": "测试"}]

    with patch("app.ai_summary._call_openai_api", return_value=""):
        questions = generate_questions(news_items)
        # 应该返回降级题目
        assert len(questions) > 0
        assert questions[0]["type"] in ["单选题", "判断题", "材料概括题"]


def test_prompt_templates():
    """测试提示词模板"""
    news_items = [
        {"title": "标题1", "summary": "摘要1", "published": "2024-01-15"},
        {"title": "标题2", "summary": "摘要2", "published": "2024-01-16"},
    ]

    # 测试摘要提示词
    summary_prompt = SUMMARY_PROMPT_TEMPLATE.format(news_items=str(news_items))
    assert "标题1" in summary_prompt
    assert "摘要1" in summary_prompt
    assert "请生成" in summary_prompt

    # 测试题目提示词
    question_prompt = QUESTION_PROMPT_TEMPLATE.format(news_items=str(news_items))
    assert "标题1" in question_prompt
    assert "摘要1" in question_prompt
    assert "公务员考试" in question_prompt


def test_model_selection():
    """测试模型选择"""
    # 测试默认模型
    with patch("app.ai_summary.os.getenv") as mock_getenv:
        mock_getenv.side_effect = lambda key, default=None: {
            "OPENAI_API_KEY": "test_key",
            "OPENAI_SUMMARY_MODEL": "gpt-4",
            "OPENAI_QUESTION_MODEL": "gpt-3.5-turbo",
        }.get(key, default)

        with patch("app.ai_summary.openai.chat.completions.create") as mock_create:
            mock_response = Mock()
            mock_choice = Mock()
            mock_choice.message.content = "测试"
            mock_response.choices = [mock_choice]
            mock_response.usage = Mock(total_tokens=10)
            mock_create.return_value = mock_response

            # 测试摘要模型
            news_items = [{"title": "测试", "summary": "测试"}]
            generate_summary(news_items)

            # 检查调用参数
            call_args = mock_create.call_args
            assert call_args is not None
            # 应该使用gpt-4模型
            assert "gpt-4" in str(call_args)


def test_error_handling():
    """测试错误处理"""
    news_items = [{"title": "测试", "summary": "测试"}]

    # 测试各种异常
    with patch("app.ai_summary._call_openai_api", side_effect=Exception("测试异常")):
        summary = generate_summary(news_items)
        # 应该返回降级结果而不是崩溃
        assert summary is not None
        assert len(summary) > 0

        questions = generate_questions(news_items)
        assert questions is not None
        assert isinstance(questions, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])