import json
import os
import random
import re
from collections import Counter
from datetime import datetime

from openai import OpenAI

SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")
QUESTION_MODEL = os.getenv("OPENAI_QUESTION_MODEL", SUMMARY_MODEL)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()


def _split_sentences(text):
    chunks = re.split(r"(?<=[。！？!?；;])", text or "")
    sentences = []
    for chunk in chunks:
        sentence = re.sub(r"\s+", " ", chunk).strip()
        if len(sentence) >= 18:
            sentences.append(sentence)
    return sentences


def _build_source_text(news_items, max_items=10):
    lines = []
    for item in news_items[:max_items]:
        published = item.get("published") or ""
        title = item.get("title") or ""
        summary = item.get("summary") or ""
        content = item.get("content") or ""
        excerpt = content[:600] if content else summary[:300]
        lines.append(f"时间：{published}\n标题：{title}\n正文摘录：{excerpt}")
    return "\n\n".join(lines)


def _count_months(news_items):
    counter = Counter()
    for item in news_items:
        published_at = item.get("published_at")
        if isinstance(published_at, datetime):
            counter[published_at.strftime("%Y-%m")] += 1
    return counter


def build_grounded_summary(news_items):
    if not news_items:
        return [
            "当前时间范围内还没有抓取到可用时政内容。",
            "可以先执行一次数据同步，再按年份或近一年视图查看。",
        ]

    month_counter = _count_months(news_items)
    first_date = news_items[-1]["published_at"].strftime("%Y-%m-%d")
    last_date = news_items[0]["published_at"].strftime("%Y-%m-%d")
    summary_lines = [
        f"当前时间范围共收录 {len(news_items)} 条时政内容，时间跨度为 {first_date} 至 {last_date}。",
    ]

    if month_counter:
        hottest_months = month_counter.most_common(3)
        month_text = "，".join(f"{month}（{count}条）" for month, count in hottest_months)
        summary_lines.append(f"内容最密集的月份为：{month_text}。")

    for item in news_items[:4]:
        summary_source = item.get("summary") or item.get("content") or item.get("title") or ""
        sentences = _split_sentences(summary_source)
        key_sentence = sentences[0] if sentences else item["title"]
        summary_lines.append(f"{item['published']}：{key_sentence}")

    return summary_lines


def _client():
    if not OPENAI_API_KEY:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)


def generate_summary(news_items):
    client = _client()
    if not client:
        return build_grounded_summary(news_items)

    source_text = _build_source_text(news_items)
    if not source_text:
        return build_grounded_summary(news_items)

    response = client.responses.create(
        model=SUMMARY_MODEL,
        input=(
            "你是一个只允许基于材料作答的时政摘要助手。"
            "请只依据给定材料，输出 4 到 6 条中文要点。"
            "如果材料没有提供的信息，不要补充。"
            f"\n\n材料如下：\n{source_text}"
        ),
    )
    text = (response.output_text or "").strip()
    lines = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
    return lines or build_grounded_summary(news_items)


def build_grounded_questions(news_items):
    if len(news_items) < 4:
        return []

    rng = random.Random(42)
    questions = []

    recent_items = news_items[: min(8, len(news_items))]
    target = recent_items[0]
    distractors = [item["title"] for item in recent_items[1:4]]
    options = [target["title"], *distractors]
    rng.shuffle(options)
    questions.append(
        {
            "type": "单选题",
            "stem": f"根据材料，以下哪一项出现在 {target['published'][:7]} 的时政内容中？",
            "options": options,
            "answer": target["title"],
            "analysis": f"材料中明确收录了《{target['title']}》，发布日期为 {target['published']}。",
        }
    )

    second = recent_items[1]
    questions.append(
        {
            "type": "判断题",
            "stem": f"判断正误：材料显示，《{second['title']}》发布于 {second['published'][:7]}。",
            "options": ["正确", "错误"],
            "answer": "正确",
            "analysis": f"该条材料发布时间为 {second['published']}，与题干一致。",
        }
    )

    third = recent_items[2]
    excerpt = _split_sentences(third.get("summary") or third.get("content") or third["title"])
    prompt_text = excerpt[0] if excerpt else third["title"]
    questions.append(
        {
            "type": "材料概括题",
            "stem": f"请根据材料，概括《{third['title']}》的核心信息。",
            "options": [],
            "answer": prompt_text,
            "analysis": "作答时应只围绕材料原文，不应扩展材料之外的信息。",
        }
    )

    month_counter = _count_months(news_items)
    if month_counter:
        month, count = month_counter.most_common(1)[0]
        questions.append(
            {
                "type": "数据分析题",
                "stem": "根据当前筛选范围，哪个月份收录的时政内容最多？",
                "options": [month] + [value for value, _ in month_counter.most_common(4)[1:4]],
                "answer": month,
                "analysis": f"系统统计显示，{month} 共收录 {count} 条内容，为当前范围内最多。",
            }
        )

    return questions


def generate_questions(news_items):
    client = _client()
    grounded_questions = build_grounded_questions(news_items)
    if not client or not news_items:
        return grounded_questions

    source_text = _build_source_text(news_items, max_items=8)
    response = client.responses.create(
        model=QUESTION_MODEL,
        input=(
            "请只根据给定时政材料，生成 4 道中文题目，风格接近公务员考试，"
            "题型包含单选、判断、材料概括。"
            "请输出 JSON 数组，每个元素包含 type、stem、options、answer、analysis。"
            "如果材料不足以支持某题，请不要编造。"
            f"\n\n材料如下：\n{source_text}"
        ),
    )
    text = (response.output_text or "").strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return grounded_questions

    valid_questions = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if not item.get("stem") or not item.get("answer"):
            continue
        valid_questions.append(
            {
                "type": item.get("type", "题目"),
                "stem": item["stem"],
                "options": item.get("options") or [],
                "answer": item["answer"],
                "analysis": item.get("analysis", ""),
            }
        )

    return valid_questions or grounded_questions
