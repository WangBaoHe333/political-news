"""首页 HTML 片段渲染。"""

from collections import OrderedDict
from html import escape
from typing import Any, Dict, List

from app.models import News


def render_summary(items: List[str]) -> str:
    return "".join(f"<li>{escape(line)}</li>" for line in items)


def render_questions(questions: List[Dict[str, Any]]) -> str:
    cards = []
    for index, question in enumerate(questions, start=1):
        options_html = "".join(f"<li>{escape(option)}</li>" for option in question["options"])
        cards.append(
            f"""
            <article class="question-card">
              <div class="question-type">{escape(question['type'])} {index}</div>
              <h4>{escape(question['stem'])}</h4>
              <ul>{options_html}</ul>
              <p><strong>参考答案：</strong>{escape(question['answer'])}</p>
              <p><strong>解析：</strong>{escape(question['analysis'])}</p>
            </article>
            """
        )
    return "".join(cards)


def render_news(groups: OrderedDict[str, List[News]]) -> str:
    sections = []
    for month_label, items in groups.items():
        articles = []
        for item in items:
            content_excerpt = escape((item.summary or item.content or "")[:220])
            articles.append(
                f"""
                <article class="news-card">
                  <div class="news-meta">{escape(item.published)} · {escape(item.source)}</div>
                  <h4><a href="{escape(item.link)}" target="_blank" rel="noreferrer">{escape(item.title)}</a></h4>
                  <p>{content_excerpt}</p>
                </article>
                """
            )
        sections.append(
            f"""
            <section class="month-block">
              <div class="month-title">{month_label}</div>
              {''.join(articles)}
            </section>
            """
        )
    return "".join(sections)


def render_today_news(items: List[News], section_title: str) -> str:
    if not items:
        return f"<div class='empty-state'>{escape(section_title)} 暂无内容。</div>"

    cards = []
    for item in items[:8]:
        cards.append(
            f"""
            <article class="news-card">
              <div class="news-meta">{escape(item.published)} · {escape(item.source)}</div>
              <h4><a href="{escape(item.link)}" target="_blank" rel="noreferrer">{escape(item.title)}</a></h4>
              <p>{escape((item.summary or item.content or '')[:180])}</p>
            </article>
            """
        )
    return f"<h2>{escape(section_title)}</h2>{''.join(cards)}"
