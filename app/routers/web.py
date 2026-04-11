"""时政资料库 Web 页面。"""

from collections import OrderedDict
from datetime import datetime
from html import escape
import json
import math
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.news_data import (
    count_news_records,
    get_news_by_id,
    get_year_counts,
    group_by_month,
    latest_news_date,
    query_news,
    source_label,
    today_news,
    yesterday_news,
)
from app.sync_service import get_app_state, get_sync_status

router = APIRouter(tags=["页面"])

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
MIN_FILTER_YEAR = 2025
ITEMS_PER_PAGE = 12
MONTHS_PER_PAGE = 4


def _filter_items_by_source(items: Sequence, selected_source: Optional[str]) -> List:
    if not selected_source:
        return list(items)
    return [item for item in items if item.source == selected_source]


def _source_counts(items: Sequence) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        source = item.source or "unknown"
        counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items(), key=lambda entry: (-entry[1], source_label(entry[0]))))


def _highlight_text(text: str, keyword: Optional[str]) -> str:
    safe_text = escape(text or "")
    needle = (keyword or "").strip()
    if not needle:
        return safe_text

    escaped_needle = escape(needle)
    pattern = re.compile(re.escape(escaped_needle), re.IGNORECASE)
    return pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", safe_text)


def _paginate_sequence(items: Sequence, page: int, page_size: int) -> Tuple[Sequence, int, int]:
    if not items:
        return items, 1, 1

    total_pages = max(1, math.ceil(len(items) / page_size))
    current_page = min(max(page, 1), total_pages)
    start = (current_page - 1) * page_size
    end = start + page_size
    return items[start:end], current_page, total_pages


def _build_href(path: str, **params: Optional[object]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "", False)}
    if not clean:
        return path
    return f"{path}?{urlencode(clean)}"


def _render_pager(path: str, current_page: int, total_pages: int, **params: Optional[object]) -> str:
    if total_pages <= 1:
        return ""

    links = []
    if current_page > 1:
        links.append(
            f"<a class='pager-link' href='{_build_href(path, page=current_page - 1, **params)}'>上一页</a>"
        )

    start = max(1, current_page - 2)
    end = min(total_pages, current_page + 2)
    for page in range(start, end + 1):
        class_name = "pager-link current" if page == current_page else "pager-link"
        links.append(
            f"<a class='{class_name}' href='{_build_href(path, page=page, **params)}'>{page}</a>"
        )

    if current_page < total_pages:
        links.append(
            f"<a class='pager-link' href='{_build_href(path, page=current_page + 1, **params)}'>下一页</a>"
        )
    return "<nav class='pager'>" + "".join(links) + "</nav>"


def _render_news_card(item, keyword: Optional[str] = None) -> str:
    title = _highlight_text(item.title, keyword)
    link = escape(item.link)
    published = escape(item.published or item.published_at.strftime("%Y-%m-%d"))
    source = escape(source_label(item.source))
    excerpt = _highlight_text((item.summary or item.content or item.title or "")[:180], keyword)
    return (
        "<article class='news-card'>"
        f"<div class='news-meta'><span>{published}</span><span>{source}</span></div>"
        f"<h4><a href='/news/{item.id}'>{title}</a></h4>"
        f"<p>{excerpt}</p>"
        "<div class='card-actions'>"
        f"<a class='inline-link' href='/news/{item.id}'>站内查看</a>"
        f"<a class='inline-link' href='{link}' target='_blank' rel='noreferrer'>查看原文</a>"
        "</div>"
        "</article>"
    )


def _render_news_stream(items, empty_text: str, keyword: Optional[str] = None) -> str:
    if not items:
        return f"<div class='empty-state'>{escape(empty_text)}</div>"
    return "".join(_render_news_card(item, keyword=keyword) for item in items)


def _render_recent_updates(items, empty_text: str) -> str:
    if not items:
        return f"<div class='empty-state'>{escape(empty_text)}</div>"

    blocks = []
    for item in items[:6]:
        published = escape(item.published or item.published_at.strftime("%Y-%m-%d"))
        source = escape(source_label(item.source))
        blocks.append(
            "<article class='mini-card'>"
            f"<div class='mini-date'>{published} · {source}</div>"
            f"<h4><a href='/news/{item.id}'>{escape(item.title)}</a></h4>"
            f"<p>{escape((item.summary or item.content or item.title or '')[:110])}</p>"
            "</article>"
        )
    return "".join(blocks)


def _render_month_groups(groups: "OrderedDict[str, List]", keyword: Optional[str] = None) -> str:
    if not groups:
        return "<div class='empty-state'>当前时间范围内没有可展示的按月归档内容。</div>"

    sections = []
    for month_label, items in groups.items():
        sections.append(
            "<details class='month-block'>"
            f"<summary class='month-title'><span>{escape(month_label)}</span><strong>{len(items)} 条</strong></summary>"
            f"<div class='month-body'>{''.join(_render_news_card(item, keyword=keyword) for item in items)}</div>"
            "</details>"
        )
    return "".join(sections)


def _visible_years(year_counts: Dict[int, int], current_year: int, selected_year: Optional[int] = None) -> List[int]:
    years = set(range(current_year, MIN_FILTER_YEAR - 1, -1))
    years.update(year for year in year_counts if year >= MIN_FILTER_YEAR)
    if selected_year:
        years.add(selected_year)
    return sorted((year for year in years if year >= MIN_FILTER_YEAR), reverse=True)


def _render_year_select(year_counts: Dict[int, int], current_year: int, selected_year: Optional[int]) -> str:
    options = ['<option value="">全部年份</option>']
    for year in _visible_years(year_counts, current_year, selected_year):
        selected = " selected" if year == selected_year else ""
        count_text = f" ({year_counts.get(year, 0)})" if year_counts.get(year, 0) else ""
        options.append(f"<option value='{year}'{selected}>{year}年{count_text}</option>")
    return "".join(options)


def _render_source_select(source_counts: Dict[str, int], selected_source: Optional[str]) -> str:
    options = ['<option value="">全部来源</option>']
    sources = list(source_counts.keys())
    if selected_source and selected_source not in source_counts:
        sources.append(selected_source)

    for source in sources:
        selected = " selected" if source == selected_source else ""
        count_text = f" ({source_counts.get(source, 0)})" if source_counts.get(source, 0) else ""
        options.append(
            f"<option value='{escape(source)}'{selected}>{escape(source_label(source))}{count_text}</option>"
        )
    return "".join(options)


def _render_year_grid(year_counts: Dict[int, int], current_year: int) -> str:
    years = _visible_years(year_counts, current_year)
    if not years:
        return "<div class='empty-state'>当前还没有可展示的年份数据。</div>"

    cards = []
    for year in years:
        count = year_counts.get(year, 0)
        cards.append(
            "<a class='year-card' href='{}'>"
            "<strong>{}</strong>"
            "<span>{} 条时政</span>"
            "</a>".format(_build_href(f"/year/{year}"), year, count)
        )
    return "<div class='year-grid'>" + "".join(cards) + "</div>"


def _render_source_grid(source_counts: Dict[str, int], active_source: Optional[str], path: str, **params) -> str:
    if not source_counts and not active_source:
        return "<div class='empty-state'>当前还没有可展示的来源分布。</div>"

    chips = [
        "<a class='source-chip{}' href='{}'>全部来源</a>".format(
            " active" if not active_source else "",
            _build_href(path, source=None, **params),
        )
    ]

    for source, count in source_counts.items():
        chips.append(
            "<a class='source-chip{}' href='{}'>{} <span>{}</span></a>".format(
                " active" if source == active_source else "",
                _build_href(path, source=source, **params),
                escape(source_label(source)),
                count,
            )
        )
    return "<div class='source-grid'>" + "".join(chips) + "</div>"


def _render_sync_panel(task_status: Dict[str, object], last_sync_at: str, last_sync_result: str) -> str:
    status_label = "进行中" if task_status["in_progress"] else "空闲"
    scope = task_status["scope"] or "最近一次任务"
    message = task_status["message"] or "当前没有运行中的同步任务。"
    started_at = task_status["started_at"] or "暂无记录"
    finished_at = task_status["finished_at"] or "暂无记录"
    last_result = last_sync_result or "尚未有成功同步记录。"
    busy_class = "status-badge busy" if task_status["in_progress"] else "status-badge"
    sync_admin_token = get_settings().sync_admin_token
    action_html = (
        """
      <div class="actions compact-actions">
        <form method="get" action="/sync-view">
          <input type="hidden" name="months" value="24" />
          <button type="submit">同步近两年到数据库</button>
        </form>
        <form method="get" action="/sync-view">
          <input type="hidden" name="year" value="{current_year}" />
          <button type="submit">同步本年</button>
        </form>
      </div>
        """.format(current_year=datetime.now(LOCAL_TZ).year)
        if not sync_admin_token
        else """
      <div class="notice compact">
        <strong>管理员提示：</strong>当前已启用同步令牌保护，公开页面只展示状态。手动同步请在服务器侧携带令牌调用接口。
      </div>
        """
    )

    return f"""
    <section class="panel" id="sync-panel">
      <div class="panel-head">
        <div>
          <h2>同步状态</h2>
          <div class="panel-subtitle">页面会自动刷新这里的状态，不需要再跳去纯 JSON 接口。</div>
        </div>
        <span class="{busy_class}" id="sync-badge">{escape(status_label)}</span>
      </div>
      <div class="sync-grid">
        <div class="sync-item"><strong>任务范围</strong><span id="sync-scope">{escape(str(scope))}</span></div>
        <div class="sync-item"><strong>最近同步</strong><span id="sync-last-at">{escape(last_sync_at)}</span></div>
        <div class="sync-item"><strong>开始时间</strong><span id="sync-started-at">{escape(str(started_at))}</span></div>
        <div class="sync-item"><strong>结束时间</strong><span id="sync-finished-at">{escape(str(finished_at))}</span></div>
      </div>
      <div class="notice compact" id="sync-message"><strong>当前状态：</strong>{escape(str(message))}</div>
      <div class="notice compact" id="sync-last-result"><strong>最近结果：</strong>{escape(last_result)}</div>
      {action_html}
    </section>
    """


def _render_article_body(item) -> str:
    content = (item.content or "").strip()
    summary = (item.summary or "").strip()
    body_text = content or summary
    if not body_text:
        return "<div class='empty-state'>这条内容暂时没有抓到正文，建议点击原文查看。</div>"

    paragraphs = [segment.strip() for segment in re.split(r"[\r\n]+", body_text) if segment.strip()]
    if not paragraphs:
        paragraphs = [body_text]
    return "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)


def _render_nav(active_tab: str) -> str:
    tabs = [
        ("latest", "/", "最新时政"),
        ("today", "/today", "今日时政"),
        ("yesterday", "/yesterday", "昨日时政"),
        ("archive", "/archive", "按月归档"),
        ("years", "/years", "年份切换"),
        ("search", "/search", "搜索"),
        ("status", "/status", "同步状态"),
    ]

    links = []
    for key, href, label in tabs:
        class_name = "nav-link active" if key == active_tab else "nav-link"
        links.append(f"<a class='{class_name}' href='{href}'>{label}</a>")
    return "".join(links)


def _render_layout(
    *,
    active_tab: str,
    hero_title: str,
    hero_text: str,
    stats: Iterable[Tuple[str, str]],
    main_html: str,
    side_html: str,
    year_counts: Dict[int, int],
    source_counts: Dict[str, int],
    current_year: int,
    selected_year: Optional[int] = None,
    selected_source: Optional[str] = None,
    search_query: str = "",
    page_title: Optional[str] = None,
) -> HTMLResponse:
    stats_html = "".join(
        f"<div class='stat'><strong>{escape(label)}</strong><span>{escape(value)}</span></div>"
        for label, value in stats
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <meta http-equiv="refresh" content="3600" />
      <title>{escape(page_title or hero_title)}</title>
      <style>
        :root {{
          --bg: #f5f0e7;
          --panel: rgba(255,255,255,0.86);
          --ink: #16202a;
          --muted: #61707d;
          --accent: #a0322d;
          --accent-2: #235c79;
          --line: rgba(35,43,51,0.12);
          --shadow: 0 18px 40px rgba(37,31,24,0.08);
        }}
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          color: var(--ink);
          font-family: "Noto Serif SC", "Songti SC", "STSong", serif;
          background:
            radial-gradient(circle at top left, rgba(160, 50, 45, 0.14), transparent 28%),
            radial-gradient(circle at top right, rgba(35, 92, 121, 0.12), transparent 26%),
            linear-gradient(180deg, #faf4ea 0%, var(--bg) 100%);
        }}
        a {{ color: inherit; text-decoration: none; }}
        .shell {{ max-width: 1220px; margin: 0 auto; padding: 22px 16px 44px; }}
        .hero {{
          border: 1px solid var(--line);
          border-radius: 28px;
          background: linear-gradient(135deg, rgba(255,255,255,0.96), rgba(247,240,231,0.92));
          box-shadow: var(--shadow);
          padding: 24px;
        }}
        .eyebrow {{
          display: inline-flex;
          align-items: center;
          padding: 7px 12px;
          border-radius: 999px;
          background: rgba(160, 50, 45, 0.08);
          color: var(--accent);
          font-size: 13px;
          font-weight: 700;
          letter-spacing: 0.06em;
          text-transform: uppercase;
        }}
        .hero h1 {{
          margin: 12px 0 8px;
          font-size: clamp(30px, 4vw, 46px);
          line-height: 1.08;
        }}
        .hero p {{
          margin: 0;
          max-width: 860px;
          color: var(--muted);
          line-height: 1.75;
        }}
        .nav-row {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          margin-top: 16px;
        }}
        .nav-link, .pager-link {{
          display: inline-flex;
          align-items: center;
          justify-content: center;
          padding: 10px 14px;
          min-height: 42px;
          border-radius: 999px;
          border: 1px solid var(--line);
          background: rgba(255,255,255,0.86);
          color: var(--ink);
          transition: transform 0.15s ease, opacity 0.15s ease;
        }}
        .nav-link.active, .pager-link.current {{
          background: var(--accent);
          border-color: transparent;
          color: white;
        }}
        .nav-link:hover, .pager-link:hover {{
          transform: translateY(-1px);
          opacity: 0.96;
        }}
        .toolbar {{
          display: grid;
          gap: 12px;
          margin-top: 16px;
        }}
        .search-form, .actions {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
        }}
        .search-form {{
          padding: 10px 12px;
          border: 1px solid var(--line);
          border-radius: 999px;
          background: rgba(255,255,255,0.88);
        }}
        .search-form input {{
          flex: 1 1 320px;
          border: 0;
          background: transparent;
          outline: none;
          color: var(--ink);
          font: inherit;
        }}
        .search-form select,
        button {{
          font: inherit;
        }}
        .search-form select {{
          border: 1px solid var(--line);
          border-radius: 999px;
          padding: 10px 14px;
          min-height: 42px;
          background: rgba(255,255,255,0.94);
        }}
        button {{
          padding: 10px 16px;
          min-height: 42px;
          border: 1px solid transparent;
          border-radius: 999px;
          background: var(--accent);
          color: white;
          cursor: pointer;
        }}
        .ghost-link {{
          display: inline-flex;
          align-items: center;
          min-height: 42px;
          padding: 10px 16px;
          border-radius: 999px;
          background: rgba(35, 92, 121, 0.96);
          color: white;
        }}
        .stats {{
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 12px;
          margin-top: 16px;
        }}
        .stat {{
          padding: 14px;
          border-radius: 18px;
          background: rgba(255,255,255,0.84);
          border: 1px solid var(--line);
        }}
        .stat strong {{
          display: block;
          margin-bottom: 8px;
          color: var(--muted);
          font-size: 13px;
        }}
        .stat span {{
          font-size: 18px;
          font-weight: 700;
        }}
        .layout {{
          display: grid;
          grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.95fr);
          gap: 18px;
          margin-top: 18px;
          align-items: start;
        }}
        .side-stack {{
          display: grid;
          gap: 18px;
        }}
        .panel {{
          border: 1px solid var(--line);
          border-radius: 24px;
          background: var(--panel);
          box-shadow: var(--shadow);
          padding: 20px;
        }}
        .panel h2 {{
          margin: 0 0 12px;
          font-size: 24px;
        }}
        .panel-head {{
          display: flex;
          justify-content: space-between;
          align-items: baseline;
          gap: 12px;
          flex-wrap: wrap;
          margin-bottom: 12px;
        }}
        .panel-subtitle {{
          color: var(--muted);
          font-size: 14px;
          line-height: 1.7;
        }}
        .news-card {{
          padding: 14px 0;
        }}
        .news-card + .news-card,
        .mini-card + .mini-card {{
          border-top: 1px solid rgba(35,43,51,0.08);
        }}
        .news-meta {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          margin-bottom: 6px;
          color: var(--muted);
          font-size: 13px;
        }}
        .news-meta span + span::before {{
          content: "·";
          margin-right: 10px;
          color: #97a5b2;
        }}
        .news-card h4, .mini-card h4 {{
          margin: 0 0 6px;
          line-height: 1.55;
        }}
        .news-card h4 {{ font-size: 18px; }}
        .mini-card h4 {{ font-size: 16px; margin-top: 6px; }}
        .news-card p, .mini-card p {{
          margin: 0;
          color: #2d3740;
          line-height: 1.72;
        }}
        .card-actions {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          margin-top: 10px;
        }}
        .inline-link {{
          display: inline-flex;
          align-items: center;
          padding: 7px 12px;
          border-radius: 999px;
          background: rgba(35, 92, 121, 0.08);
          color: var(--accent-2);
          font-size: 13px;
          font-weight: 700;
        }}
        .mini-card {{
          padding: 12px 0;
        }}
        .mini-date {{
          font-size: 12px;
          color: var(--muted);
        }}
        .source-grid {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }}
        .source-chip {{
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 10px 12px;
          border-radius: 999px;
          border: 1px solid var(--line);
          background: rgba(255,255,255,0.76);
          color: var(--ink);
          font-size: 14px;
        }}
        .source-chip span {{
          color: var(--muted);
          font-size: 12px;
        }}
        .source-chip.active {{
          background: var(--accent);
          border-color: transparent;
          color: white;
        }}
        .source-chip.active span {{
          color: rgba(255,255,255,0.82);
        }}
        .year-grid {{
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 12px;
        }}
        .year-card {{
          padding: 16px;
          border-radius: 18px;
          border: 1px solid var(--line);
          background: rgba(255,255,255,0.74);
        }}
        .year-card strong {{
          display: block;
          font-size: 22px;
          color: var(--accent);
          margin-bottom: 6px;
        }}
        .year-card span {{
          color: var(--muted);
          font-size: 14px;
        }}
        .sync-grid {{
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
          margin-top: 6px;
        }}
        .sync-item {{
          padding: 12px;
          border-radius: 16px;
          border: 1px solid rgba(35,43,51,0.08);
          background: rgba(255,255,255,0.72);
        }}
        .sync-item strong {{
          display: block;
          font-size: 12px;
          color: var(--muted);
          margin-bottom: 5px;
        }}
        .sync-item span {{
          font-size: 14px;
          line-height: 1.5;
        }}
        .status-badge {{
          display: inline-flex;
          align-items: center;
          padding: 7px 12px;
          border-radius: 999px;
          background: rgba(35, 92, 121, 0.12);
          color: var(--accent-2);
          font-size: 13px;
          font-weight: 700;
        }}
        .status-badge.busy {{
          background: rgba(160, 50, 45, 0.12);
          color: var(--accent);
        }}
        .notice {{
          margin-top: 12px;
          padding: 13px 14px;
          border-radius: 16px;
          border: 1px solid var(--line);
          background: rgba(255,255,255,0.78);
          line-height: 1.7;
        }}
        .compact {{ margin-top: 10px; }}
        .compact-actions {{
          margin-top: 10px;
        }}
        details.month-block {{
          border: 1px solid rgba(35,43,51,0.08);
          border-radius: 18px;
          background: rgba(255,255,255,0.7);
          padding: 0 14px 8px;
        }}
        details.month-block + details.month-block {{
          margin-top: 14px;
        }}
        summary.month-title {{
          list-style: none;
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 10px;
          cursor: pointer;
          margin: 0 -14px;
          padding: 14px;
          color: var(--accent);
          font-weight: 700;
        }}
        summary.month-title::-webkit-details-marker {{
          display: none;
        }}
        summary.month-title::after {{
          content: "展开";
          color: var(--muted);
          font-size: 12px;
          font-weight: 600;
        }}
        details[open] > summary.month-title::after {{
          content: "收起";
        }}
        .pager {{
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 18px;
        }}
        .pager-link {{
          background: rgba(35, 92, 121, 0.92);
          color: white;
          border: 0;
        }}
        .pager-link.current {{
          background: var(--accent);
          pointer-events: none;
        }}
        .empty-state {{
          padding: 18px;
          border-radius: 18px;
          border: 1px dashed rgba(160,50,45,0.28);
          background: rgba(255,248,242,0.84);
          color: #5c4640;
          line-height: 1.8;
        }}
        .helper-list {{
          display: grid;
          gap: 10px;
        }}
        .helper-chip {{
          display: inline-flex;
          align-items: center;
          padding: 8px 12px;
          border-radius: 999px;
          border: 1px solid var(--line);
          background: rgba(255,255,255,0.76);
          font-size: 14px;
        }}
        .article-shell {{
          display: grid;
          gap: 18px;
        }}
        .article-meta-grid {{
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 10px;
        }}
        .article-body {{
          display: grid;
          gap: 14px;
          line-height: 1.9;
          font-size: 17px;
        }}
        .article-body p {{
          margin: 0;
        }}
        mark {{
          padding: 0 4px;
          border-radius: 6px;
          background: rgba(255, 206, 92, 0.72);
          color: inherit;
        }}
        @media (max-width: 1080px) {{
          .layout {{ grid-template-columns: 1fr; }}
          .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
          .article-meta-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        }}
        @media (max-width: 720px) {{
          .shell {{ padding-inline: 12px; }}
          .hero {{ padding: 20px; }}
          .stats, .sync-grid, .article-meta-grid {{ grid-template-columns: 1fr; }}
        }}
      </style>
    </head>
    <body>
      <main class="shell">
        <section class="hero">
          <div class="eyebrow">Political News System</div>
          <h1>{escape(hero_title)}</h1>
          <p>{escape(hero_text)}</p>

          <div class="nav-row">{_render_nav(active_tab)}</div>

          <div class="toolbar">
            <form method="get" action="/search" class="search-form">
              <input type="text" name="q" value="{escape(search_query)}" placeholder="搜索标题、正文、来源或日期关键词" />
              <select name="year">{_render_year_select(year_counts, current_year, selected_year)}</select>
              <select name="source">{_render_source_select(source_counts, selected_source)}</select>
              <button type="submit">搜索数据库</button>
              <a class="ghost-link" href="/status">去同步页面</a>
            </form>
          </div>

          <div class="stats">{stats_html}</div>
        </section>

        <section class="layout">
          <div>{main_html}</div>
          <aside class="side-stack">{side_html}</aside>
        </section>
      </main>

      <script>
        async function refreshSyncStatus() {{
          const badge = document.getElementById('sync-badge');
          if (!badge) return;
          try {{
            const response = await fetch('/sync-status', {{ cache: 'no-store' }});
            if (!response.ok) return;
            const data = await response.json();
            const scope = document.getElementById('sync-scope');
            const lastAt = document.getElementById('sync-last-at');
            const startedAt = document.getElementById('sync-started-at');
            const finishedAt = document.getElementById('sync-finished-at');
            const message = document.getElementById('sync-message');
            const lastResult = document.getElementById('sync-last-result');

            const busy = Boolean(data.in_progress);
            badge.textContent = busy ? '进行中' : '空闲';
            badge.classList.toggle('busy', busy);
            if (scope) scope.textContent = data.scope || '最近一次任务';
            if (lastAt) lastAt.textContent = data.last_sync_at || {json.dumps(get_app_state("last_sync_at", "尚未同步"), ensure_ascii=False)};
            if (startedAt) startedAt.textContent = data.started_at || '暂无记录';
            if (finishedAt) finishedAt.textContent = data.finished_at || '暂无记录';
            if (message) message.innerHTML = '<strong>当前状态：</strong>' + (data.message || '当前没有运行中的同步任务。');
            if (lastResult) lastResult.innerHTML = '<strong>最近结果：</strong>' + (data.last_result || '尚未有成功同步记录。');
          }} catch (error) {{
            console.warn('sync status refresh failed', error);
          }}
        }}

        refreshSyncStatus();
        setInterval(refreshSyncStatus, 10000);
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)


def _shared_sidebar(
    year_counts: Dict[int, int],
    current_year: int,
    recent_items,
    source_counts: Dict[str, int],
    source_path: str,
    active_source: Optional[str] = None,
    **source_params,
) -> str:
    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>年份入口</h2><div class='panel-subtitle'>点击年份进入独立页面查看该年的全部时政。</div></div></div>"
        + _render_year_grid(year_counts, current_year)
        + "</section>"
        + "<section class='panel'>"
        "<div class='panel-head'><div><h2>来源筛选</h2><div class='panel-subtitle'>上线后用户最常见的动作之一，就是按来源快速缩小范围。</div></div></div>"
        + _render_source_grid(source_counts, active_source, source_path, **source_params)
        + "</section>"
        + "<section class='panel'>"
        "<div class='panel-head'><div><h2>最近更新</h2><div class='panel-subtitle'>这里展示数据库里最新写入的时政内容。</div></div></div>"
        + _render_recent_updates(recent_items, "当前还没有最近更新内容。")
        + "</section>"
    )


@router.get("/", response_class=HTMLResponse)
@router.get("/latest", response_class=HTMLResponse)
async def latest_page(
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
):
    current_year = datetime.now(LOCAL_TZ).year
    all_recent_items, _ = query_news(year=None, search=None, months=24)
    source_counts = _source_counts(all_recent_items)
    recent_items = _filter_items_by_source(all_recent_items, source)
    page_items, current_page, total_pages = _paginate_sequence(recent_items, page, ITEMS_PER_PAGE)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)
    latest_date = latest_news_date(all_recent_items)

    main_html = (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>最新时政</h2><div class='panel-subtitle'>全部内容直接从数据库读取，按发布时间倒序展示。</div></div>"
        f"<span>{len(recent_items)} 条</span></div>"
        + _render_news_stream(page_items, "数据库中还没有最近两年的时政内容，请先同步。")
        + _render_pager("/", current_page, total_pages, source=source)
        + "</section>"
    )

    side_html = _shared_sidebar(
        year_counts,
        current_year,
        all_recent_items,
        source_counts,
        "/",
        active_source=source,
    )
    stats = [
        ("数据库总条数", str(count_news_records())),
        ("最近两年条数", str(len(all_recent_items))),
        ("当前来源", source_label(source) if source else "全部来源"),
        ("最新发布日期", latest_date.strftime("%Y-%m-%d") if latest_date else "暂无数据"),
    ]
    return _render_layout(
        active_tab="latest",
        hero_title="最新时政",
        hero_text="这里是最适合日常打开的主界面。所有内容直接从数据库读取，不再把多个视图堆在同一页里。",
        stats=stats,
        main_html=main_html,
        side_html=side_html,
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_source=source,
        page_title="最新时政",
    )


@router.get("/today", response_class=HTMLResponse)
async def today_page(
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
):
    current_year = datetime.now(LOCAL_TZ).year
    all_recent_items, _ = query_news(year=None, search=None, months=24)
    source_counts = _source_counts(all_recent_items)
    filtered_recent_items = _filter_items_by_source(all_recent_items, source)
    items, title = today_news(filtered_recent_items, limit=None)
    page_items, current_page, total_pages = _paginate_sequence(items, page, ITEMS_PER_PAGE)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)

    main_html = (
        "<section class='panel'>"
        f"<div class='panel-head'><div><h2>{escape(title)}</h2><div class='panel-subtitle'>只显示数据库里日期为今天的内容。</div></div><span>{len(items)} 条</span></div>"
        + _render_news_stream(page_items, "今天还没有抓取到时政内容。")
        + _render_pager("/today", current_page, total_pages, source=source)
        + "</section>"
    )

    return _render_layout(
        active_tab="today",
        hero_title="今日时政",
        hero_text="适合当天快速刷一遍。这里只显示数据库中归档为今天的时政内容。",
        stats=[
            ("今日条数", str(len(items))),
            ("数据库总条数", str(count_news_records())),
            ("年份覆盖", f"{min(_visible_years(year_counts, current_year), default=current_year)}-{current_year}"),
            ("当前来源", source_label(source) if source else "全部来源"),
        ],
        main_html=main_html,
        side_html=_shared_sidebar(
            year_counts,
            current_year,
            all_recent_items,
            source_counts,
            "/today",
            active_source=source,
        ),
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_source=source,
        page_title="今日时政",
    )


@router.get("/yesterday", response_class=HTMLResponse)
async def yesterday_page(
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
):
    current_year = datetime.now(LOCAL_TZ).year
    all_recent_items, _ = query_news(year=None, search=None, months=24)
    source_counts = _source_counts(all_recent_items)
    filtered_recent_items = _filter_items_by_source(all_recent_items, source)
    items, title = yesterday_news(filtered_recent_items, limit=None)
    page_items, current_page, total_pages = _paginate_sequence(items, page, ITEMS_PER_PAGE)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)

    main_html = (
        "<section class='panel'>"
        f"<div class='panel-head'><div><h2>{escape(title)}</h2><div class='panel-subtitle'>单独拎出来做一页，方便回看昨天的重要信息。</div></div><span>{len(items)} 条</span></div>"
        + _render_news_stream(page_items, "昨天还没有抓取到时政内容。")
        + _render_pager("/yesterday", current_page, total_pages, source=source)
        + "</section>"
    )

    return _render_layout(
        active_tab="yesterday",
        hero_title="昨日时政",
        hero_text="如果你是隔天集中看新闻，这页会比长首页更顺手。",
        stats=[
            ("昨日条数", str(len(items))),
            ("数据库总条数", str(count_news_records())),
            ("年份覆盖", f"{min(_visible_years(year_counts, current_year), default=current_year)}-{current_year}"),
            ("当前来源", source_label(source) if source else "全部来源"),
        ],
        main_html=main_html,
        side_html=_shared_sidebar(
            year_counts,
            current_year,
            all_recent_items,
            source_counts,
            "/yesterday",
            active_source=source,
        ),
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_source=source,
        page_title="昨日时政",
    )


@router.get("/archive", response_class=HTMLResponse)
async def archive_page(
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
):
    current_year = datetime.now(LOCAL_TZ).year
    all_recent_items, _ = query_news(year=None, search=None, months=24)
    source_counts = _source_counts(all_recent_items)
    recent_items = _filter_items_by_source(all_recent_items, source)
    groups = group_by_month(recent_items)
    entries = list(groups.items())
    page_entries, current_page, total_pages = _paginate_sequence(entries, page, MONTHS_PER_PAGE)
    visible_groups = OrderedDict(page_entries)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)

    main_html = (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>按月归档</h2><div class='panel-subtitle'>默认折叠显示，每页只看少量月份，避免页面过长。</div></div>"
        f"<span>{len(groups)} 个月</span></div>"
        + _render_month_groups(visible_groups)
        + _render_pager("/archive", current_page, total_pages, source=source)
        + "</section>"
    )

    return _render_layout(
        active_tab="archive",
        hero_title="按月归档",
        hero_text="适合系统复习。每个月是独立折叠块，展开后查看该月全部时政内容。",
        stats=[
            ("归档月份", str(len(groups))),
            ("最近两年条数", str(len(all_recent_items))),
            ("数据库总条数", str(count_news_records())),
            ("当前来源", source_label(source) if source else "全部来源"),
        ],
        main_html=main_html,
        side_html=_shared_sidebar(
            year_counts,
            current_year,
            all_recent_items,
            source_counts,
            "/archive",
            active_source=source,
        ),
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_source=source,
        page_title="按月归档",
    )


@router.get("/years", response_class=HTMLResponse)
async def years_page():
    current_year = datetime.now(LOCAL_TZ).year
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)
    recent_items, _ = query_news(year=None, search=None, months=24)
    source_counts = _source_counts(recent_items)

    main_html = (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>年份切换</h2><div class='panel-subtitle'>每个年份都是独立页面，避免在首页里混用筛选器。</div></div></div>"
        + _render_year_grid(year_counts, current_year)
        + "</section>"
    )

    return _render_layout(
        active_tab="years",
        hero_title="年份切换",
        hero_text="从这里进入某个年份的独立页面查看，不再把所有年份塞进一个下拉框里强行复用。",
        stats=[
            ("可查看年份", str(len(_visible_years(year_counts, current_year)))),
            ("最早年份", str(min(_visible_years(year_counts, current_year), default=current_year))),
            ("数据库总条数", str(count_news_records())),
            ("最近两年条数", str(len(recent_items))),
        ],
        main_html=main_html,
        side_html=_shared_sidebar(
            year_counts,
            current_year,
            recent_items,
            source_counts,
            "/years",
        ),
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        page_title="年份切换",
    )


@router.get("/year/{year}", response_class=HTMLResponse)
async def year_detail_page(
    year: int,
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
):
    current_year = datetime.now(LOCAL_TZ).year
    all_items, _ = query_news(year=year, search=None, months=None)
    source_counts = _source_counts(all_items)
    items = _filter_items_by_source(all_items, source)
    page_items, current_page, total_pages = _paginate_sequence(items, page, ITEMS_PER_PAGE)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)
    recent_items, _ = query_news(year=None, search=None, months=24)

    main_html = (
        "<section class='panel'>"
        f"<div class='panel-head'><div><h2>{year} 年时政</h2><div class='panel-subtitle'>该页面只展示 {year} 年的数据库内容。</div></div><span>{len(items)} 条</span></div>"
        + _render_news_stream(page_items, f"{year} 年还没有同步到数据库。")
        + _render_pager(f"/year/{year}", current_page, total_pages, source=source)
        + "</section>"
    )

    return _render_layout(
        active_tab="years",
        hero_title=f"{year} 年时政",
        hero_text="这是年份独立页面，适合按年梳理资料，不需要在首页里来回切换。",
        stats=[
            ("年份", str(year)),
            ("当年条数", str(len(all_items))),
            ("数据库总条数", str(count_news_records())),
            ("当前来源", source_label(source) if source else "全部来源"),
        ],
        main_html=main_html,
        side_html=_shared_sidebar(
            year_counts,
            current_year,
            recent_items,
            source_counts,
            f"/year/{year}",
            active_source=source,
        ),
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_year=year,
        selected_source=source,
        page_title=f"{year} 年时政",
    )


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    q: Optional[str] = Query(default=None),
    year: Optional[int] = Query(default=None),
    source: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
):
    current_year = datetime.now(LOCAL_TZ).year
    keyword = (q or "").strip()
    items = []
    source_counts: Dict[str, int] = {}
    if keyword:
        raw_items, _ = query_news(year=year, search=keyword, months=None)
        source_counts = _source_counts(raw_items)
        items = _filter_items_by_source(raw_items, source)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)
    recent_items, _ = query_news(year=None, search=None, months=24)
    page_items, current_page, total_pages = _paginate_sequence(items, page, ITEMS_PER_PAGE)

    subtitle = "输入关键词后会直接在数据库中搜索标题、摘要、正文、来源和日期。"
    if year:
        subtitle = f"当前把搜索范围限制在 {year} 年。"
    if source:
        subtitle += f" 当前来源筛选为 {source_label(source)}。"

    main_html = (
        "<section class='panel'>"
        f"<div class='panel-head'><div><h2>搜索结果</h2><div class='panel-subtitle'>{escape(subtitle)}</div></div><span>{len(items)} 条</span></div>"
        + (
            _render_news_stream(page_items, "请输入关键词后开始搜索。" if not keyword else f"没有找到关键词「{keyword}」匹配的内容。", keyword=keyword)
        )
        + _render_pager("/search", current_page, total_pages, q=keyword, year=year, source=source)
        + "</section>"
    )

    side_html = (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>搜索提示</h2><div class='panel-subtitle'>建议使用会议、政策、人物、地区或发布日期关键词组合检索。</div></div></div>"
        "<div class='helper-list'>"
        "<span class='helper-chip'>例：中央政治局</span>"
        "<span class='helper-chip'>例：政府工作报告</span>"
        "<span class='helper-chip'>例：2025-03</span>"
        "<span class='helper-chip'>例：人民网</span>"
        "</div>"
        "</section>"
        + _shared_sidebar(
            year_counts,
            current_year,
            recent_items,
            source_counts,
            "/search",
            active_source=source,
            q=keyword,
            year=year,
        )
    )

    return _render_layout(
        active_tab="search",
        hero_title="搜索数据库",
        hero_text="搜索页只做一件事：从数据库里查。这样结果更直接，也更容易理解。",
        stats=[
            ("搜索关键词", keyword or "未输入"),
            ("命中结果", str(len(items))),
            ("年份限制", str(year) if year else "全部年份"),
            ("当前来源", source_label(source) if source else "全部来源"),
        ],
        main_html=main_html,
        side_html=side_html,
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_year=year,
        selected_source=source,
        search_query=keyword,
        page_title="搜索数据库",
    )


@router.get("/news/{news_id}", response_class=HTMLResponse)
async def news_detail_page(news_id: int):
    item = get_news_by_id(news_id)
    if item is None:
        return HTMLResponse(
            content="<h1>未找到内容</h1><p>这条时政可能尚未同步，或者已经不存在。</p>",
            status_code=404,
        )

    current_year = datetime.now(LOCAL_TZ).year
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)
    recent_items, _ = query_news(year=None, search=None, months=24)
    source_counts = _source_counts(recent_items)
    related_items = [
        related
        for related in recent_items
        if related.id != item.id and (related.source == item.source or related.year == item.year)
    ][:6]

    main_html = (
        "<section class='panel article-shell'>"
        "<div class='panel-head'><div><h2>站内详情</h2><div class='panel-subtitle'>上线产品后，列表页应该能自然进入详情页，而不是直接把用户甩到外站。</div></div></div>"
        "<div class='article-meta-grid'>"
        f"<div class='sync-item'><strong>发布日期</strong><span>{escape(item.published or item.published_at.strftime('%Y-%m-%d'))}</span></div>"
        f"<div class='sync-item'><strong>来源</strong><span>{escape(source_label(item.source))}</span></div>"
        f"<div class='sync-item'><strong>年份</strong><span>{item.year} 年</span></div>"
        f"<div class='sync-item'><strong>月份</strong><span>{item.month} 月</span></div>"
        "</div>"
        "<div class='actions'>"
        f"<a class='ghost-link' href='{escape(item.link)}' target='_blank' rel='noreferrer'>查看原文</a>"
        f"<a class='ghost-link' href='{_build_href(f'/year/{item.year}', source=item.source)}'>查看同年同来源</a>"
        "</div>"
        f"<div class='notice'><strong>摘要：</strong>{escape(item.summary or '暂无摘要')}</div>"
        f"<div class='article-body'>{_render_article_body(item)}</div>"
        "</section>"
    )

    side_html = (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>相关推荐</h2><div class='panel-subtitle'>优先展示同来源或同年份的近篇内容，减少读完一条就断开的感觉。</div></div></div>"
        + _render_recent_updates(related_items, "当前没有可推荐的相关文章。")
        + "</section>"
        + _shared_sidebar(
            year_counts,
            current_year,
            recent_items,
            source_counts,
            f"/year/{item.year}",
            active_source=item.source,
        )
    )

    return _render_layout(
        active_tab="latest",
        hero_title=item.title,
        hero_text="详情页让数据库内容真正变成可阅读的产品，而不只是一个跳板列表。",
        stats=[
            ("来源", source_label(item.source)),
            ("发布日期", item.published or item.published_at.strftime("%Y-%m-%d")),
            ("年份", f"{item.year} 年"),
            ("数据库总条数", str(count_news_records())),
        ],
        main_html=main_html,
        side_html=side_html,
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_year=item.year,
        selected_source=item.source,
        page_title=item.title,
    )


@router.get("/status", response_class=HTMLResponse)
async def status_page(sync_status: str = Query(default="")):
    current_year = datetime.now(LOCAL_TZ).year
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)
    recent_items, _ = query_news(year=None, search=None, months=24)
    source_counts = _source_counts(recent_items)
    task_status = get_sync_status()
    last_sync_at = get_app_state("last_sync_at", "尚未同步")
    last_sync_result = sync_status or get_app_state("last_sync_result", "")

    main_html = _render_sync_panel(task_status, last_sync_at, last_sync_result)
    side_html = _shared_sidebar(
        year_counts,
        current_year,
        recent_items,
        source_counts,
        "/status",
    )

    return _render_layout(
        active_tab="status",
        hero_title="同步状态",
        hero_text="这里专门负责同步相关信息和按钮，不再把同步说明塞进首页角落里。",
        stats=[
            ("当前状态", "进行中" if task_status["in_progress"] else "空闲"),
            ("最近同步", last_sync_at),
            ("数据库总条数", str(count_news_records())),
            ("最近两年条数", str(len(recent_items))),
        ],
        main_html=main_html,
        side_html=side_html,
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        page_title="同步状态",
    )
