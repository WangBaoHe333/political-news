"""时政资料库 Web 首页。"""

from collections import OrderedDict
from datetime import datetime
from html import escape
import json
import math
import re
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.news_data import group_by_month, latest_news_date, query_news, today_news, yesterday_news
from app.sync_service import get_app_state, get_sync_status

router = APIRouter(tags=["页面"])
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
MIN_FILTER_YEAR = 2025
MONTHS_PER_PAGE = 6


def _highlight_text(text: str, keyword: Optional[str]) -> str:
    safe_text = escape(text or "")
    needle = (keyword or "").strip()
    if not needle:
        return safe_text

    escaped_needle = escape(needle)
    pattern = re.compile(re.escape(escaped_needle), re.IGNORECASE)
    return pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", safe_text)


def _render_news_card(item, keyword: Optional[str] = None) -> str:
    title = _highlight_text(item.title, keyword)
    link = escape(item.link)
    published = escape(item.published or item.published_at.strftime("%Y-%m-%d"))
    source = escape(item.source or "unknown")
    excerpt = _highlight_text((item.summary or item.content or item.title or "")[:180], keyword)
    return (
        "<article class='news-card'>"
        f"<div class='news-meta'><span>{published}</span><span>{source}</span></div>"
        f"<h4><a href='{link}' target='_blank' rel='noreferrer'>{title}</a></h4>"
        f"<p>{excerpt}</p>"
        "</article>"
    )


def _render_news_list(items, empty_text: str, limit: int = 6, keyword: Optional[str] = None) -> str:
    if not items:
        return f"<div class='empty-state'>{escape(empty_text)}</div>"
    return "".join(_render_news_card(item, keyword=keyword) for item in items[:limit])


def _render_recent_updates(items, keyword: Optional[str] = None, limit: int = 6) -> str:
    if not items:
        return "<div class='empty-state'>当前还没有可展示的最近更新。</div>"

    blocks = []
    for item in items[:limit]:
        title = _highlight_text(item.title, keyword)
        excerpt = _highlight_text((item.summary or item.content or item.title or "")[:110], keyword)
        published = escape(item.published or item.published_at.strftime("%Y-%m-%d"))
        source = escape(item.source or "unknown")
        blocks.append(
            "<article class='mini-card'>"
            f"<div class='mini-date'>{published} · {source}</div>"
            f"<h4><a href='{escape(item.link)}' target='_blank' rel='noreferrer'>{title}</a></h4>"
            f"<p>{excerpt}</p>"
            "</article>"
        )
    return "".join(blocks)


def _paginate_month_groups(groups, page: int, per_page: int = MONTHS_PER_PAGE):
    entries = list(groups.items())
    if not entries:
        return OrderedDict(), 1, 1

    total_pages = max(1, math.ceil(len(entries) / per_page))
    current_page = min(max(page, 1), total_pages)
    start = (current_page - 1) * per_page
    end = start + per_page
    return OrderedDict(entries[start:end]), current_page, total_pages


def _render_month_groups(groups, keyword: Optional[str] = None) -> str:
    if not groups:
        return "<div class='empty-state'>当前筛选范围内没有可展示的时政内容。</div>"

    sections = []
    for month_label, items in groups.items():
        cards = "".join(_render_news_card(item, keyword=keyword) for item in items)
        sections.append(
            "<details class='month-block'>"
            f"<summary class='month-title'><span>{escape(month_label)}</span><strong>{len(items)} 条</strong></summary>"
            f"<div class='month-body'>{cards}</div>"
            "</details>"
        )
    return "".join(sections)


def _build_year_options(current_year: int, years, selected_year: Optional[int]) -> str:
    visible_years = set(range(current_year, MIN_FILTER_YEAR - 1, -1))
    visible_years.update(year for year in years if year >= MIN_FILTER_YEAR)
    if selected_year:
        visible_years.add(selected_year)

    ordered = sorted((year for year in visible_years if year >= MIN_FILTER_YEAR), reverse=True)
    options = ['<option value="">近两年</option>']
    for value in ordered:
        selected = " selected" if selected_year == value else ""
        options.append(f'<option value="{value}"{selected}>{value}年</option>')
    return "".join(options)


def _build_page_url(page: int, year: Optional[int], keyword: Optional[str]) -> str:
    params = {"page": page}
    if year:
        params["year"] = year
    if keyword:
        params["q"] = keyword
    return f"/?{urlencode(params)}#archive"


def _render_pagination(current_page: int, total_pages: int, year: Optional[int], keyword: Optional[str]) -> str:
    if total_pages <= 1:
        return ""

    links = []
    if current_page > 1:
        links.append(f"<a class='pager-link' href='{_build_page_url(current_page - 1, year, keyword)}'>上一页</a>")

    start = max(1, current_page - 2)
    end = min(total_pages, current_page + 2)
    for page in range(start, end + 1):
        class_name = "pager-link current" if page == current_page else "pager-link"
        links.append(f"<a class='{class_name}' href='{_build_page_url(page, year, keyword)}'>{page}</a>")

    if current_page < total_pages:
        links.append(f"<a class='pager-link' href='{_build_page_url(current_page + 1, year, keyword)}'>下一页</a>")

    return "<nav class='pager'>" + "".join(links) + "</nav>"


def _render_sync_panel(task_status, last_sync_at: str, last_sync_result: str) -> str:
    status_label = "进行中" if task_status["in_progress"] else "空闲"
    message = task_status["message"] or "当前没有运行中的同步任务。"
    scope = task_status["scope"] or "最近一次任务"
    started_at = task_status["started_at"] or "暂无记录"
    finished_at = task_status["finished_at"] or "暂无记录"
    latest = last_sync_result or "尚未有成功同步记录。"

    return f"""
    <section class="panel sync-panel" id="sync-panel">
      <div class="panel-head">
        <div>
          <h2>同步状态</h2>
          <div class="panel-subtitle">页面内实时可见，每 10 秒自动刷新一次。</div>
        </div>
        <span class="status-badge" id="sync-badge">{escape(status_label)}</span>
      </div>
      <div class="sync-grid">
        <div class="sync-item">
          <strong>任务范围</strong>
          <span id="sync-scope">{escape(scope)}</span>
        </div>
        <div class="sync-item">
          <strong>最近同步时间</strong>
          <span id="sync-last-at">{escape(last_sync_at)}</span>
        </div>
        <div class="sync-item">
          <strong>开始时间</strong>
          <span id="sync-started-at">{escape(started_at)}</span>
        </div>
        <div class="sync-item">
          <strong>结束时间</strong>
          <span id="sync-finished-at">{escape(finished_at)}</span>
        </div>
      </div>
      <div class="notice compact" id="sync-message"><strong>当前状态：</strong>{escape(message)}</div>
      <div class="notice compact" id="sync-last-result"><strong>最近结果：</strong>{escape(latest)}</div>
      <div class="actions compact-actions">
        <form method="get" action="/sync-view">
          <input type="hidden" name="months" value="1" />
          <button type="submit">刷新最新内容</button>
        </form>
        <form method="get" action="/sync-view">
          <input type="hidden" name="months" value="24" />
          <button type="submit">同步近两年</button>
        </form>
      </div>
    </section>
    """


@router.get("/", response_class=HTMLResponse)
async def read_news(
    year: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    sync_status: str = Query(default=""),
):
    current_year = datetime.now(LOCAL_TZ).year
    archive_items, years = query_news(year=year, search=q, months=24)
    all_groups = group_by_month(archive_items)
    visible_groups, current_page, total_pages = _paginate_month_groups(all_groups, page)

    recent_items, _ = query_news(year=None, search=None, months=24)
    context_items = archive_items if (year or q) else recent_items
    today_items, today_title = today_news(context_items)
    yesterday_items, yesterday_title = yesterday_news(context_items)

    last_sync_at = get_app_state("last_sync_at", "尚未同步")
    last_sync_result = sync_status or get_app_state("last_sync_result", "")
    latest_published_at = latest_news_date(recent_items)
    task_status = get_sync_status()

    selected_year = str(year) if year else "近两年"
    latest_value = latest_published_at.strftime("%Y-%m-%d") if latest_published_at else "暂无数据"
    result_label = f"共命中 {len(archive_items)} 条"
    if q:
        result_label = f"关键词「{q}」命中 {len(archive_items)} 条"

    if year:
        range_label = f"当前查看 {year} 年内容，默认按月份归档，展开即可阅读。"
    else:
        range_label = "默认展示最近两年的时政内容，按月份归档并支持分页查看。"

    empty_state = ""
    if not archive_items:
        if year and q:
            empty_message = f"没有找到 {year} 年、关键词「{q}」匹配的时政内容。"
        elif year:
            empty_message = f"当前暂无 {year} 年时政内容，请先同步或切换年份。"
        elif q:
            empty_message = f"没有找到关键词「{q}」匹配的时政内容。"
        else:
            empty_message = "当前近两年的时政内容为空，请先同步数据。"
        empty_state = f"<div class='empty-state empty-wide'>{escape(empty_message)}</div>"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <meta http-equiv="refresh" content="3600" />
      <title>时政资料库</title>
      <style>
        :root {{
          --bg: #f6f1e8;
          --panel: rgba(255, 255, 255, 0.84);
          --ink: #16202a;
          --muted: #617180;
          --accent: #a0302d;
          --accent-2: #235c79;
          --line: rgba(35, 43, 51, 0.12);
          --shadow: 0 18px 42px rgba(37, 31, 24, 0.08);
        }}
        * {{ box-sizing: border-box; }}
        html {{ scroll-behavior: smooth; }}
        body {{
          margin: 0;
          color: var(--ink);
          font-family: "Noto Serif SC", "Songti SC", "STSong", serif;
          background:
            radial-gradient(circle at top left, rgba(160, 48, 45, 0.14), transparent 30%),
            radial-gradient(circle at top right, rgba(35, 92, 121, 0.12), transparent 28%),
            linear-gradient(180deg, #f9f3ea 0%, var(--bg) 100%);
        }}
        a {{ color: inherit; text-decoration: none; }}
        .shell {{ max-width: 1240px; margin: 0 auto; padding: 24px 16px 48px; }}
        .hero {{
          border: 1px solid var(--line);
          border-radius: 28px;
          background: linear-gradient(135deg, rgba(255,255,255,0.96), rgba(248,241,233,0.9));
          box-shadow: var(--shadow);
          padding: 24px;
        }}
        .eyebrow {{
          display: inline-flex;
          align-items: center;
          padding: 7px 12px;
          border-radius: 999px;
          background: rgba(160, 48, 45, 0.08);
          color: var(--accent);
          font-size: 13px;
          font-weight: 700;
          letter-spacing: 0.06em;
          text-transform: uppercase;
        }}
        .hero h1 {{
          margin: 12px 0 8px;
          font-size: clamp(32px, 4vw, 48px);
          line-height: 1.08;
        }}
        .hero p {{
          margin: 0;
          max-width: 820px;
          color: var(--muted);
          line-height: 1.75;
        }}
        .toolbar {{
          margin-top: 18px;
          display: grid;
          gap: 12px;
        }}
        .toolbar form,
        .toolbar .actions {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
        }}
        .search-box {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          align-items: center;
          padding: 10px 12px;
          border: 1px solid var(--line);
          border-radius: 999px;
          background: rgba(255,255,255,0.88);
        }}
        .search-box input,
        .search-box select,
        select, button, .ghost-link {{
          font: inherit;
        }}
        .search-box input {{
          flex: 1 1 320px;
          border: 0;
          background: transparent;
          outline: none;
          color: var(--ink);
          font-size: 15px;
        }}
        .search-box input::placeholder {{ color: #8b98a6; }}
        select {{
          border: 1px solid var(--line);
          border-radius: 999px;
          background: rgba(255,255,255,0.94);
          padding: 10px 16px;
          min-height: 42px;
        }}
        button, .ghost-link, .pager-link {{
          border: 1px solid transparent;
          border-radius: 999px;
          padding: 10px 16px;
          min-height: 42px;
          background: var(--accent);
          color: white;
          cursor: pointer;
          transition: transform 0.15s ease, opacity 0.15s ease;
        }}
        button:hover, .ghost-link:hover, .pager-link:hover {{ transform: translateY(-1px); opacity: 0.96; }}
        .ghost-link {{ background: rgba(35, 92, 121, 0.95); }}
        .chip-row {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          margin-top: 6px;
        }}
        .chip {{
          display: inline-flex;
          align-items: center;
          padding: 8px 12px;
          border-radius: 999px;
          border: 1px solid var(--line);
          background: rgba(255,255,255,0.76);
          font-size: 14px;
        }}
        mark {{
          padding: 0 4px;
          border-radius: 6px;
          background: rgba(255, 206, 92, 0.72);
          color: inherit;
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
        .notice {{
          margin-top: 12px;
          padding: 13px 14px;
          border-radius: 16px;
          border: 1px solid var(--line);
          background: rgba(255,255,255,0.78);
          line-height: 1.7;
        }}
        .compact {{ margin-top: 10px; }}
        .layout {{
          display: grid;
          grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.9fr);
          gap: 18px;
          margin-top: 18px;
          align-items: start;
        }}
        .panel {{
          border: 1px solid var(--line);
          border-radius: 24px;
          background: var(--panel);
          backdrop-filter: blur(10px);
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
        .side-stack {{
          display: grid;
          gap: 18px;
        }}
        .news-card {{
          padding: 14px 0;
        }}
        .news-card + .news-card {{
          border-top: 1px solid rgba(35, 43, 51, 0.08);
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
          color: #9aa8b4;
        }}
        .news-card h4 {{
          margin: 0 0 6px;
          font-size: 18px;
          line-height: 1.55;
        }}
        .news-card p {{
          margin: 0;
          color: #2d3740;
          line-height: 1.72;
        }}
        .mini-card + .mini-card {{
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px solid rgba(35, 43, 51, 0.08);
        }}
        .mini-card h4 {{
          margin: 5px 0 6px;
          font-size: 16px;
          line-height: 1.5;
        }}
        .mini-card p {{
          margin: 0;
          font-size: 14px;
          color: #2e3942;
          line-height: 1.68;
        }}
        .mini-date {{
          color: var(--muted);
          font-size: 12px;
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
          border: 1px solid rgba(35, 43, 51, 0.08);
          background: rgba(255,255,255,0.74);
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
          background: rgba(160, 48, 45, 0.12);
          color: var(--accent);
        }}
        .compact-actions {{
          margin-top: 10px;
        }}
        details.month-block {{
          border: 1px solid rgba(35, 43, 51, 0.08);
          border-radius: 18px;
          background: rgba(255,255,255,0.68);
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
        .month-body {{
          padding-bottom: 6px;
        }}
        .pager {{
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 18px;
        }}
        .pager-link {{
          background: rgba(35, 92, 121, 0.92);
          font-size: 14px;
        }}
        .pager-link.current {{
          background: var(--accent);
          pointer-events: none;
        }}
        .empty-state {{
          padding: 18px;
          border-radius: 18px;
          border: 1px dashed rgba(160, 48, 45, 0.28);
          background: rgba(255, 248, 242, 0.84);
          line-height: 1.8;
          color: #5b4540;
        }}
        .empty-wide {{ margin-top: 16px; }}
        .small-link {{
          color: var(--accent-2);
          font-size: 14px;
          font-weight: 700;
        }}
        @media (max-width: 1080px) {{
          .layout {{ grid-template-columns: 1fr; }}
          .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        }}
        @media (max-width: 720px) {{
          .shell {{ padding-inline: 12px; }}
          .hero {{ padding: 20px; }}
          .stats {{ grid-template-columns: 1fr; }}
          .sync-grid {{ grid-template-columns: 1fr; }}
          .panel {{ padding: 18px; }}
        }}
      </style>
    </head>
    <body>
      <main class="shell">
        <section class="hero">
          <div class="eyebrow">Political News System</div>
          <h1>时政资料库</h1>
          <p>{escape(range_label)}</p>

          <div class="toolbar">
            <form method="get" action="/" class="search-box">
              <input type="text" name="q" value="{escape(q or '')}" placeholder="搜索标题、正文、来源、日期或栏目关键词" />
              <select name="year">{_build_year_options(current_year, years, year)}</select>
              <button type="submit">搜索</button>
              <a class="small-link" href="/">清空</a>
            </form>
            <div class="actions">
              <form method="get" action="/sync-view">
                <input type="hidden" name="year" value="{current_year}" />
                <button type="submit">同步本年</button>
              </form>
              <form method="get" action="/backfill-view">
                <input type="hidden" name="months" value="24" />
                <button type="submit">分批回填近两年</button>
              </form>
              <a class="ghost-link" href="#sync-panel">查看同步状态</a>
            </div>
          </div>

          <div class="chip-row">
            <a class="chip" href="#archive">按月归档</a>
            <a class="chip" href="#today-news">今日时政</a>
            <a class="chip" href="#yesterday-news">昨日时政</a>
            <a class="chip" href="#recent-updates">最近更新</a>
            <span class="chip">{escape(selected_year)}</span>
          </div>

          <div class="stats">
            <div class="stat"><strong>当前筛选</strong><span>{escape(selected_year)}</span></div>
            <div class="stat"><strong>结果总数</strong><span>{escape(result_label)}</span></div>
            <div class="stat"><strong>最新发布日期</strong><span>{escape(latest_value)}</span></div>
            <div class="stat"><strong>归档页码</strong><span>第 {current_page} / {total_pages} 页</span></div>
          </div>
        </section>

        {empty_state}

        <section class="layout">
          <section class="panel" id="archive">
            <div class="panel-head">
              <div>
                <h2>按月归档</h2>
                <div class="panel-subtitle">默认折叠显示，每页展示 {MONTHS_PER_PAGE} 个月。需要时展开具体月份阅读。</div>
              </div>
              <span class="small-link">共 {len(all_groups)} 个月</span>
            </div>
            {_render_month_groups(visible_groups, keyword=q)}
            {_render_pagination(current_page, total_pages, year, q)}
          </section>

          <aside class="side-stack">
            {_render_sync_panel(task_status, last_sync_at, last_sync_result)}

            <section class="panel" id="today-news">
              <div class="panel-head">
                <div>
                  <h2>{escape(today_title)}</h2>
                  <div class="panel-subtitle">基于当前筛选条件动态显示。</div>
                </div>
                <span class="small-link">{len(today_items)} 条</span>
              </div>
              {_render_news_list(today_items, "当前筛选下没有今日时政内容。", keyword=q)}
            </section>

            <section class="panel" id="yesterday-news">
              <div class="panel-head">
                <div>
                  <h2>{escape(yesterday_title)}</h2>
                  <div class="panel-subtitle">方便快速回看昨天的重要信息。</div>
                </div>
                <span class="small-link">{len(yesterday_items)} 条</span>
              </div>
              {_render_news_list(yesterday_items, "当前筛选下没有昨日时政内容。", keyword=q)}
            </section>

            <section class="panel" id="recent-updates">
              <div class="panel-head">
                <div>
                  <h2>最近更新</h2>
                  <div class="panel-subtitle">优先看最新入库内容，减少整页滚动负担。</div>
                </div>
                <span class="small-link">{min(len(context_items), 6)} 条</span>
              </div>
              {_render_recent_updates(context_items, keyword=q)}
            </section>
          </aside>
        </section>
      </main>

      <script>
        async function refreshSyncStatus() {{
          try {{
            const response = await fetch('/sync-status', {{ cache: 'no-store' }});
            if (!response.ok) return;
            const data = await response.json();
            const badge = document.getElementById('sync-badge');
            const scope = document.getElementById('sync-scope');
            const lastAt = document.getElementById('sync-last-at');
            const startedAt = document.getElementById('sync-started-at');
            const finishedAt = document.getElementById('sync-finished-at');
            const message = document.getElementById('sync-message');
            const lastResult = document.getElementById('sync-last-result');

            const busy = Boolean(data.in_progress);
            badge.textContent = busy ? '进行中' : '空闲';
            badge.classList.toggle('busy', busy);
            scope.textContent = data.scope || '最近一次任务';
            lastAt.textContent = data.last_sync_at || {json.dumps(last_sync_at, ensure_ascii=False)};
            startedAt.textContent = data.started_at || '暂无记录';
            finishedAt.textContent = data.finished_at || '暂无记录';
            message.innerHTML = '<strong>当前状态：</strong>' + (data.message || '当前没有运行中的同步任务。');
            lastResult.innerHTML = '<strong>最近结果：</strong>' + (data.last_result || '尚未有成功同步记录。');
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
    return HTMLResponse(content=html_content, status_code=200)
