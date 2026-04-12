"""时政资料库 Web 页面。"""

from collections import OrderedDict
from datetime import datetime
from html import escape
import json
import math
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.news_data import (
    CATEGORY_DEFINITIONS,
    category_from_slug,
    category_label,
    count_news_records,
    get_news_by_id,
    get_year_counts,
    group_by_month,
    query_news,
    source_label,
    source_trust_label,
    source_trust_note,
    today_news,
    yesterday_news,
)
from app.sync_service import get_app_state, get_sync_status

router = APIRouter(tags=["页面"])

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
MIN_FILTER_YEAR = 2025
ITEMS_PER_PAGE = 8
MONTHS_PER_PAGE = 3
TRUSTED_SOURCE_ORDER = ("gov_cn", "people_cn", "xinhuanet", "cctv", "mfa", "chinanews")


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


def _category_counts(items: Sequence) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        label = category_label(getattr(item, "category", None))
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])))


def _filter_items_by_category(items: Sequence, selected_category: Optional[str]) -> List:
    if not selected_category:
        return list(items)
    normalized = category_label(selected_category)
    return [item for item in items if category_label(getattr(item, "category", None)) == normalized]


def _highlight_text(text: str, keyword: Optional[str]) -> str:
    safe_text = escape(text or "")
    needle = (keyword or "").strip()
    if not needle:
        return safe_text

    escaped_needle = escape(needle)
    pattern = re.compile(re.escape(escaped_needle), re.IGNORECASE)
    return pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", safe_text)


def _source_hostname(link: str) -> str:
    hostname = urlparse(link).hostname or ""
    return hostname.removeprefix("www.")


def _render_source_signature(item) -> str:
    source = escape(source_label(item.source))
    category = escape(category_label(getattr(item, "category", None)))
    trust = escape(source_trust_label(item.source))
    hostname = escape(_source_hostname(item.link))
    return (
        "<div class='meta-cluster'>"
        f"<span class='meta-pill source'>{source}</span>"
        f"<span class='meta-pill category'>{category}</span>"
        f"<span class='meta-pill trust'>{trust}</span>"
        f"<span class='meta-pill domain'>{hostname}</span>"
        "</div>"
    )


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
    excerpt = _highlight_text((item.summary or item.content or item.title or "")[:180], keyword)
    return (
        "<article class='news-card'>"
        f"<div class='news-meta'><span>{published}</span><span>原文摘录</span></div>"
        f"{_render_source_signature(item)}"
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


def _render_scroll_shell(content: str, variant: str = "stream") -> str:
    return f"<div class='scroll-shell {variant}'>{content}</div>"


def _render_category_shelves(items: Sequence, limit_categories: int = 4, per_category: int = 4) -> str:
    grouped: Dict[str, List] = {}
    for item in items:
        label = category_label(getattr(item, "category", None))
        grouped.setdefault(label, []).append(item)

    sections = []
    for label, slug in ((label, slug) for slug, label in CATEGORY_DEFINITIONS.items()):
        bucket = grouped.get(label, [])
        if not bucket:
            continue
        sections.append(
            "<section class='panel'>"
            "<div class='panel-head'>"
            f"<div><h2>{escape(label)}</h2><div class='panel-subtitle'>按专题聚合近两年内容，减少用户在不同站点之间来回跳。</div></div>"
            f"<a class='inline-link' href='/category/{slug}'>进入专题</a>"
            "</div>"
            + _render_scroll_shell(
                "".join(_render_news_card(item) for item in bucket[:per_category]),
                variant="shelf",
            )
            + "</section>"
        )
        if len(sections) >= limit_categories:
            break
    return "".join(sections)


def _render_recent_updates(items, empty_text: str) -> str:
    if not items:
        return f"<div class='empty-state'>{escape(empty_text)}</div>"

    blocks = []
    for item in items[:6]:
        published = escape(item.published or item.published_at.strftime("%Y-%m-%d"))
        blocks.append(
            "<article class='mini-card'>"
            f"<div class='mini-date'>{published} · {escape(source_label(item.source))}</div>"
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
    effective_year = selected_year or current_year
    options = []
    for year in _visible_years(year_counts, current_year, effective_year):
        selected = " selected" if year == effective_year else ""
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


def _render_category_overview(category_counts: Dict[str, int]) -> str:
    if not category_counts:
        return "<div class='empty-state'>当前还没有形成可用的分类数据。</div>"

    cards = []
    for slug, label in CATEGORY_DEFINITIONS.items():
        count = category_counts.get(label, 0)
        cards.append(
            "<a class='category-card' href='{}'>"
            "<strong>{}</strong>"
            "<span>{} 条</span>"
            "</a>".format(_build_href(f"/category/{slug}"), escape(label), count)
        )
    return "<div class='category-grid'>" + "".join(cards) + "</div>"


def _render_source_overview(source_counts: Dict[str, int]) -> str:
    if not source_counts:
        return "<div class='empty-state'>当前还没有可展示的数据源概况。</div>"

    cards = []
    for source in TRUSTED_SOURCE_ORDER:
        count = source_counts.get(source, 0)
        cards.append(
            "<a class='category-card source-card' href='{}'>"
            "<strong>{}</strong>"
            "<span>{} 条</span>"
            "</a>".format(f"/source/{source}", escape(source_label(source)), count)
        )
    return "<div class='category-grid'>" + "".join(cards) + "</div>"


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
    source_alerts = task_status.get("source_alerts") or []
    if isinstance(source_alerts, list):
        source_alerts = [str(item) for item in source_alerts if str(item).strip()]
    else:
        source_alerts = []
    source_alert_text = "；".join(source_alerts)
    critical_sources = task_status.get("critical_sources") or []
    if isinstance(critical_sources, list):
        critical_sources = [str(item) for item in critical_sources if str(item).strip()]
    else:
        critical_sources = []
    critical_text = "、".join(source_label(source) for source in critical_sources)
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
      <div class="notice compact" id="sync-source-alerts"><strong>来源告警：</strong>{escape(source_alert_text or "无")}</div>
      <div class="notice compact" id="sync-critical-sources"><strong>连续异常来源：</strong>{escape(critical_text or "无")}</div>
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


def _render_quality_panel() -> str:
    chips = "".join(
        f"<span class='helper-chip'>{escape(source_label(source))} · {escape(source_trust_label(source))}</span>"
        for source in TRUSTED_SOURCE_ORDER
    )
    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>数据说明</h2><div class='panel-subtitle'>把可信度说清楚，比堆更多按钮更重要。</div></div></div>"
        "<div class='helper-list'>"
        "<div class='notice compact'><strong>白名单来源：</strong>当前纳入中国政府网、人民网、新华网、外交部、中国新闻网等公开权威来源。</div>"
        "<div class='notice compact'><strong>同步规则：</strong>链接域名必须匹配来源白名单，日期异常或正文过短的内容会被过滤。</div>"
        "<div class='notice compact'><strong>展示方式：</strong>站内只做原文摘录，不做 AI 改写，并始终保留原文链接。</div>"
        f"<div class='source-reference'>{chips}</div>"
        "</div>"
        "</section>"
    )


def _source_health_rows(items: Sequence) -> List[Dict[str, str]]:
    now = datetime.now(LOCAL_TZ)
    rows: List[Dict[str, str]] = []

    for source in TRUSTED_SOURCE_ORDER:
        source_items = [item for item in items if item.source == source]
        latest = max((item.published_at for item in source_items), default=None)
        count = len(source_items)

        if latest is None:
            freshness = "缺失"
            freshness_class = "stale"
            latest_text = "暂无数据"
        else:
            age_days = (now.date() - latest.date()).days
            if age_days <= 2:
                freshness = "正常"
                freshness_class = "healthy"
            elif age_days <= 7:
                freshness = "轻微延迟"
                freshness_class = "warm"
            else:
                freshness = "偏旧"
                freshness_class = "stale"
            latest_text = latest.strftime("%Y-%m-%d")

        rows.append(
            {
                "source": source_label(source),
                "trust": source_trust_label(source),
                "latest": latest_text,
                "count": str(count),
                "freshness": freshness,
                "freshness_class": freshness_class,
            }
        )
    return rows


def _render_source_health_panel(items: Sequence) -> str:
    rows = _source_health_rows(items)
    cards = []
    for row in rows:
        cards.append(
            "<article class='health-card'>"
            f"<div class='health-head'><strong>{escape(row['source'])}</strong><span class='health-badge {escape(row['freshness_class'])}'>{escape(row['freshness'])}</span></div>"
            f"<div class='health-meta'>{escape(row['trust'])}</div>"
            f"<div class='health-grid'><span>最近日期：{escape(row['latest'])}</span><span>收录条数：{escape(row['count'])}</span></div>"
            "</article>"
        )
    return (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>来源覆盖</h2><div class='panel-subtitle'>这里帮助你快速判断哪一路数据断流了、哪一路还是新鲜的。</div></div></div>"
        + "".join(cards)
        + "</section>"
    )


def _render_nav(active_tab: str) -> str:
    tabs = [
        ("today", "/", "今日时政"),
        ("yesterday", "/yesterday", "昨日时政"),
        ("categories", "/categories", "分类专题"),
        ("sources", "/sources", "数据源"),
        ("archive", "/archive", "按月归档"),
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
          gap: 10px;
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
        .toolbar-note {{
          color: var(--muted);
          font-size: 13px;
          line-height: 1.6;
          padding-inline: 4px;
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
          grid-template-columns: minmax(0, 1.72fr) minmax(280px, 0.82fr);
          gap: 18px;
          margin-top: 18px;
          align-items: start;
        }}
        .main-stack {{
          display: grid;
          gap: 18px;
        }}
        .side-stack {{
          display: grid;
          gap: 18px;
          position: sticky;
          top: 18px;
          max-height: calc(100vh - 36px);
          overflow: auto;
          padding-right: 4px;
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
        .scroll-shell {{
          margin-top: 8px;
          padding-right: 6px;
          overflow-y: auto;
          scrollbar-width: thin;
          scrollbar-color: rgba(35, 92, 121, 0.45) transparent;
        }}
        .scroll-shell.stream {{
          max-height: min(52vh, 760px);
        }}
        .scroll-shell.months {{
          max-height: min(58vh, 860px);
        }}
        .scroll-shell.shelf {{
          max-height: min(42vh, 520px);
        }}
        .scroll-shell::-webkit-scrollbar {{
          width: 8px;
        }}
        .scroll-shell::-webkit-scrollbar-thumb {{
          background: rgba(35, 92, 121, 0.3);
          border-radius: 999px;
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
        .meta-cluster {{
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 10px;
        }}
        .meta-pill {{
          display: inline-flex;
          align-items: center;
          min-height: 28px;
          padding: 5px 10px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 700;
          border: 1px solid rgba(35,43,51,0.08);
          background: rgba(255,255,255,0.72);
        }}
        .meta-pill.source {{
          color: var(--accent-2);
          background: rgba(35,92,121,0.09);
        }}
        .meta-pill.category {{
          color: #83561b;
          background: rgba(183,132,43,0.14);
        }}
        .meta-pill.trust {{
          color: var(--accent);
          background: rgba(160,50,45,0.1);
        }}
        .meta-pill.domain {{
          color: #5e6972;
          background: rgba(22,32,42,0.05);
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
        .headline-layout {{
          display: grid;
          grid-template-columns: minmax(0, 1.3fr) minmax(260px, 0.85fr);
          gap: 18px;
        }}
        .headline-lead {{
          padding: 18px;
          border-radius: 20px;
          background: rgba(255,255,255,0.72);
          border: 1px solid rgba(35,43,51,0.08);
        }}
        .headline-lead h3 {{
          margin: 0 0 10px;
          font-size: 28px;
          line-height: 1.4;
        }}
        .headline-lead p {{
          margin: 0;
          line-height: 1.8;
          color: #2d3740;
        }}
        .headline-side {{
          display: grid;
          gap: 10px;
        }}
        .headline-mini {{
          padding: 14px 16px;
          border-radius: 18px;
          background: rgba(255,255,255,0.72);
          border: 1px solid rgba(35,43,51,0.08);
        }}
        .headline-mini span {{
          display: block;
          margin-bottom: 6px;
          font-size: 12px;
          color: var(--muted);
        }}
        .headline-mini a {{
          font-size: 16px;
          line-height: 1.7;
          font-weight: 700;
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
        .category-grid {{
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
        .category-card {{
          display: block;
          padding: 16px;
          border-radius: 18px;
          border: 1px solid var(--line);
          background: rgba(255,255,255,0.74);
        }}
        .category-card strong {{
          display: block;
          font-size: 19px;
          color: var(--accent-2);
          margin-bottom: 6px;
        }}
        .category-card span {{
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
        .health-card {{
          padding: 14px 0;
        }}
        .health-card + .health-card {{
          border-top: 1px solid rgba(35,43,51,0.08);
        }}
        .health-head {{
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 6px;
        }}
        .health-meta {{
          color: var(--muted);
          font-size: 13px;
          margin-bottom: 8px;
        }}
        .health-grid {{
          display: grid;
          gap: 6px;
          color: #2d3740;
          font-size: 14px;
        }}
        .health-badge {{
          display: inline-flex;
          align-items: center;
          padding: 6px 10px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 700;
        }}
        .health-badge.healthy {{
          background: rgba(41, 122, 76, 0.12);
          color: #297a4c;
        }}
        .health-badge.warm {{
          background: rgba(184, 118, 21, 0.14);
          color: #9a5d04;
        }}
        .health-badge.stale {{
          background: rgba(160, 50, 45, 0.12);
          color: var(--accent);
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
        .source-reference {{
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
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
          .headline-layout {{ grid-template-columns: 1fr; }}
          .side-stack {{
            position: static;
            max-height: none;
            overflow: visible;
            padding-right: 0;
          }}
          .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
          .article-meta-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        }}
        @media (max-width: 720px) {{
          .shell {{ padding-inline: 12px; }}
          .hero {{ padding: 20px; }}
          .stats, .sync-grid, .article-meta-grid {{ grid-template-columns: 1fr; }}
          .scroll-shell.stream,
          .scroll-shell.months {{
            max-height: none;
            overflow: visible;
            padding-right: 0;
          }}
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
              <input type="search" name="q" value="{escape(search_query)}" placeholder="搜索标题、正文或日期，例如 2025-03、2026-04-11" />
              <select name="year">{_render_year_select(year_counts, current_year, selected_year)}</select>
              <button type="submit">搜索</button>
            </form>
            <div class="toolbar-note">搜索只保留一个入口，默认按 {current_year} 年检索；要看同步情况，直接切到上方的同步状态页。</div>
          </div>

          <div class="stats">{stats_html}</div>
        </section>

        <section class="layout">
          <div class="main-stack">{main_html}</div>
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
            const sourceAlerts = document.getElementById('sync-source-alerts');
            const criticalSources = document.getElementById('sync-critical-sources');

            const busy = Boolean(data.in_progress);
            badge.textContent = busy ? '进行中' : '空闲';
            badge.classList.toggle('busy', busy);
            if (scope) scope.textContent = data.scope || '最近一次任务';
            if (lastAt) lastAt.textContent = data.last_sync_at || {json.dumps(get_app_state("last_sync_at", "尚未同步"), ensure_ascii=False)};
            if (startedAt) startedAt.textContent = data.started_at || '暂无记录';
            if (finishedAt) finishedAt.textContent = data.finished_at || '暂无记录';
            if (message) message.innerHTML = '<strong>当前状态：</strong>' + (data.message || '当前没有运行中的同步任务。');
            if (lastResult) lastResult.innerHTML = '<strong>最近结果：</strong>' + (data.last_result || '尚未有成功同步记录。');
            if (sourceAlerts) {{
              const alerts = Array.isArray(data.source_alerts) ? data.source_alerts : [];
              sourceAlerts.innerHTML = '<strong>来源告警：</strong>' + (alerts.length ? alerts.join('；') : '无');
            }}
            if (criticalSources) {{
              const critical = Array.isArray(data.critical_sources) ? data.critical_sources : [];
              criticalSources.innerHTML = '<strong>连续异常来源：</strong>' + (critical.length ? critical.join('、') : '无');
            }}
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
        "<div class='panel-head'><div><h2>来源筛选</h2><div class='panel-subtitle'>只保留一个必要筛选，不再重复堆专题入口和来源入口。</div></div></div>"
        + _render_source_grid(source_counts, active_source, source_path, **source_params)
        + "</section>"
    )


@router.get("/latest")
async def latest_page(
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
):
    return RedirectResponse(url=_build_href("/archive", page=page, source=source), status_code=302)


@router.get("/", response_class=HTMLResponse)
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
    display_items = items or filtered_recent_items
    display_title = title if items else "今日暂无更新，已显示最近时政"
    display_subtitle = (
        "只显示数据库里日期为今天的内容，作为门户首页的主时间线。"
        if items
        else "当前还没有归档为今天的内容，首页已自动回退展示数据库里的最近更新。"
    )
    page_items, current_page, total_pages = _paginate_sequence(display_items, page, ITEMS_PER_PAGE)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)

    main_html = (
        "<section class='panel'>"
        f"<div class='panel-head'><div><h2>{escape(display_title)}</h2><div class='panel-subtitle'>{escape(display_subtitle)}</div></div><span>{len(display_items)} 条</span></div>"
        + _render_scroll_shell(_render_news_stream(page_items, "数据库里还没有可展示的内容。"))
        + _render_pager("/today", current_page, total_pages, source=source)
        + "</section>"
    )

    return _render_layout(
        active_tab="today",
        hero_title="今日时政",
        hero_text="首页只保留今日时政主列表和必要筛选。专题、来源、同步状态都回到各自独立页面，减少重复入口。",
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
        selected_year=current_year,
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
        + _render_scroll_shell(_render_news_stream(page_items, "昨天还没有抓取到时政内容。"))
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
        selected_year=current_year,
        selected_source=source,
        page_title="昨日时政",
    )


@router.get("/categories", response_class=HTMLResponse)
async def categories_page(
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
    category: str = Query(default="shizheng"),
):
    current_year = datetime.now(LOCAL_TZ).year
    all_items, _ = query_news(year=None, search=None, months=24, source=source)
    source_counts = _source_counts(all_items)
    category_counts = _category_counts(all_items)
    selected_category = category_from_slug(category)
    selected_items = _filter_items_by_category(all_items, selected_category)
    page_items, current_page, total_pages = _paginate_sequence(selected_items, page, ITEMS_PER_PAGE)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)

    main_html = (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>专题入口</h2><div class='panel-subtitle'>数据源里的分类专题统一在这里，不再分散到其他页面。</div></div></div>"
        + _render_category_overview(category_counts)
        + "</section>"
        + "<section class='panel'>"
        f"<div class='panel-head'><div><h2>{escape(selected_category)}专题</h2><div class='panel-subtitle'>当前专题下的时政内容按时间倒序展示。</div></div>"
        f"<span>{len(selected_items)} 条</span></div>"
        + _render_scroll_shell(_render_news_stream(page_items, f"当前还没有可展示的{selected_category}专题内容。"))
        + _render_pager("/categories", current_page, total_pages, source=source, category=category)
        + "</section>"
    )

    return _render_layout(
        active_tab="categories",
        hero_title="分类专题",
        hero_text="分类专题页统一承接所有专题分类入口，默认展示时政专题，并支持切换来源筛选。",
        stats=[
            ("专题数量", str(len([count for count in category_counts.values() if count > 0]))),
            ("当前专题", selected_category),
            ("数据库总条数", str(count_news_records())),
            ("当前来源", source_label(source) if source else "全部来源"),
        ],
        main_html=main_html,
        side_html=_shared_sidebar(
            year_counts,
            current_year,
            all_items,
            source_counts,
            "/categories",
            active_source=source,
            category=category,
        ),
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_year=current_year,
        selected_source=source,
        page_title="分类专题",
    )


@router.get("/category/{slug}", response_class=HTMLResponse)
async def category_detail_page(
    slug: str,
    page: int = Query(default=1, ge=1),
    source: Optional[str] = Query(default=None),
):
    current_year = datetime.now(LOCAL_TZ).year
    category_name = category_from_slug(slug)
    all_items, _ = query_news(year=None, search=None, months=24, source=source, category=category_name)
    source_counts = _source_counts(all_items)
    page_items, current_page, total_pages = _paginate_sequence(all_items, page, ITEMS_PER_PAGE)
    recent_items, _ = query_news(year=None, search=None, months=24)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)

    main_html = (
        "<section class='panel'>"
        f"<div class='panel-head'><div><h2>{escape(category_name)}</h2><div class='panel-subtitle'>按专题聚合，方便直接查看同类时政，不再把所有站点内容混在一起。</div></div><span>{len(all_items)} 条</span></div>"
        + _render_scroll_shell(_render_news_stream(page_items, f"当前还没有 {category_name} 相关内容。"))
        + _render_pager(f"/category/{slug}", current_page, total_pages, source=source)
        + "</section>"
    )

    return _render_layout(
        active_tab="categories",
        hero_title=f"{category_name}专题",
        hero_text="分类详情页负责把多站点时政按主题聚起来，用户不需要自己靠关键词猜。",
        stats=[
            ("专题", category_name),
            ("专题条数", str(len(all_items))),
            ("当前来源", source_label(source) if source else "全部来源"),
            ("数据库总条数", str(count_news_records())),
        ],
        main_html=main_html,
        side_html=_shared_sidebar(
            year_counts,
            current_year,
            recent_items,
            source_counts if source_counts else _source_counts(recent_items),
            f"/category/{slug}",
            active_source=source,
        ),
        year_counts=year_counts,
        source_counts=source_counts if source_counts else _source_counts(recent_items),
        current_year=current_year,
        selected_year=current_year,
        selected_source=source,
        page_title=f"{category_name}专题",
    )


@router.get("/sources", response_class=HTMLResponse)
async def sources_page():
    current_year = datetime.now(LOCAL_TZ).year
    recent_items, _ = query_news(year=None, search=None, months=24)
    source_counts = _source_counts(recent_items)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)

    main_html = (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>数据源</h2><div class='panel-subtitle'>来源页只负责展示站点覆盖和可信说明，不再混入专题入口。</div></div></div>"
        + _render_source_overview(source_counts)
        + "</section>"
        + _render_source_health_panel(recent_items)
    )

    return _render_layout(
        active_tab="sources",
        hero_title="数据源",
        hero_text="这里专门看来源覆盖、来源新鲜度和站点可信说明，不再和首页、专题页混在一起。",
        stats=[
            ("来源数量", str(len([count for count in source_counts.values() if count > 0]))),
            ("数据库总条数", str(count_news_records())),
            ("当前年份", str(current_year)),
            ("当前收录", str(len(recent_items))),
        ],
        main_html=main_html,
        side_html=_render_quality_panel(),
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_year=current_year,
        page_title="数据源",
    )


@router.get("/source/{source}", response_class=HTMLResponse)
async def source_detail_page(
    source: str,
    page: int = Query(default=1, ge=1),
):
    current_year = datetime.now(LOCAL_TZ).year
    all_items, _ = query_news(year=None, search=None, months=24, source=source)
    page_items, current_page, total_pages = _paginate_sequence(all_items, page, ITEMS_PER_PAGE)
    source_counts = _source_counts(all_items)
    recent_items, _ = query_news(year=None, search=None, months=24)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)
    category_counts = _category_counts(all_items)

    main_html = (
        "<section class='panel'>"
        f"<div class='panel-head'><div><h2>{escape(source_label(source))}</h2><div class='panel-subtitle'>{escape(source_trust_note(source))}</div></div><span>{len(all_items)} 条</span></div>"
        + _render_scroll_shell(_render_news_stream(page_items, f"{source_label(source)} 暂时还没有收录内容。"))
        + _render_pager(f"/source/{source}", current_page, total_pages)
        + "</section>"
        + "<section class='panel'>"
        "<div class='panel-head'><div><h2>来源内专题分布</h2><div class='panel-subtitle'>同一来源里也会有要闻、外交、人事、国际等不同专题。</div></div></div>"
        + _render_category_overview(category_counts)
        + "</section>"
    )

    return _render_layout(
        active_tab="sources",
        hero_title=f"{source_label(source)}",
        hero_text="来源详情页帮助你判断单一权威来源的覆盖面和更新质量，也方便回看该站点的全部收录。",
        stats=[
            ("来源", source_label(source)),
            ("来源级别", source_trust_label(source)),
            ("收录条数", str(len(all_items))),
            ("数据库总条数", str(count_news_records())),
        ],
        main_html=main_html,
        side_html=_shared_sidebar(
            year_counts,
            current_year,
            recent_items,
            _source_counts(recent_items),
            f"/source/{source}",
            active_source=source,
        ),
        year_counts=year_counts,
        source_counts=source_counts if source_counts else _source_counts(recent_items),
        current_year=current_year,
        selected_year=current_year,
        selected_source=source,
        page_title=source_label(source),
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
        + _render_scroll_shell(_render_month_groups(visible_groups), variant="months")
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
        selected_year=current_year,
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
        "<div class='panel-head'><div><h2>按年份浏览</h2><div class='panel-subtitle'>如果你想单独复习某一年，可以直接从这里进入对应页面。</div></div></div>"
        + _render_year_grid(year_counts, current_year)
        + "</section>"
    )

    return _render_layout(
        active_tab="archive",
        hero_title="按年份浏览",
        hero_text="年份入口保留为兼容页面，但主流程已经统一收敛到顶部搜索和归档页，减少重复按钮。",
        stats=[
            ("可查看年份", str(len(_visible_years(year_counts, current_year)))),
            ("最早年份", str(min(_visible_years(year_counts, current_year), default=current_year))),
            ("数据库总条数", str(count_news_records())),
            ("已收录条数", str(len(recent_items))),
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
        selected_year=current_year,
        page_title="按年份浏览",
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
        + _render_scroll_shell(_render_news_stream(page_items, f"{year} 年还没有同步到数据库。"))
        + _render_pager(f"/year/{year}", current_page, total_pages, source=source)
        + "</section>"
    )

    return _render_layout(
        active_tab="archive",
        hero_title=f"{year} 年时政",
        hero_text="这是年份独立页面。顶部搜索可以直接限定年份，所以这里更像按年复习时的直达页。",
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
    search_year = year or current_year
    items = []
    source_counts: Dict[str, int] = {}
    if keyword or year or source:
        raw_items, _ = query_news(year=search_year, search=keyword or None, months=None)
        source_counts = _source_counts(raw_items)
        items = _filter_items_by_source(raw_items, source)
    year_counts = get_year_counts(min_year=MIN_FILTER_YEAR)
    recent_items, _ = query_news(year=None, search=None, months=24)
    page_items, current_page, total_pages = _paginate_sequence(items, page, ITEMS_PER_PAGE)

    subtitle = f"当前默认在 {search_year} 年范围内搜索标题、摘要、正文、来源和发布日期。"
    if keyword:
        subtitle = f"当前在 {search_year} 年范围内搜索关键词。"
    elif source:
        subtitle = f"当前只查看 {search_year} 年内来自 {source_label(source)} 的内容。"
    if source and keyword:
        subtitle += f" 当前来源筛选为 {source_label(source)}。"

    main_html = (
        "<section class='panel'>"
        f"<div class='panel-head'><div><h2>搜索结果</h2><div class='panel-subtitle'>{escape(subtitle)}</div></div><span>{len(items)} 条</span></div>"
        + _render_scroll_shell(
            _render_news_stream(
                page_items,
                f"输入关键词后会默认搜索 {search_year} 年内容。"
                if not (keyword or year or source)
                else f"没有找到「{keyword or year or source_label(source)}」匹配的内容。",
                keyword=keyword,
            )
        )
        + _render_pager("/search", current_page, total_pages, q=keyword, year=year, source=source)
        + "</section>"
    )

    side_html = (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>搜索提示</h2><div class='panel-subtitle'>一个输入框就够了，日期、会议、政策、人名都可以直接搜。</div></div></div>"
        "<div class='helper-list'>"
        "<span class='helper-chip'>例：中央政治局</span>"
        "<span class='helper-chip'>例：政府工作报告</span>"
        "<span class='helper-chip'>例：2025-03</span>"
        "<span class='helper-chip'>例：2026-04-11</span>"
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
        hero_title="搜索",
        hero_text="搜索页现在只保留一个统一入口，输入关键词或选年份就能查，避免出现两个含义相同的搜索按钮。",
        stats=[
            ("关键词", keyword or "未输入"),
            ("命中结果", str(len(items))),
            ("年份限制", str(search_year)),
            ("当前来源", source_label(source) if source else "全部来源"),
        ],
        main_html=main_html,
        side_html=side_html,
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        selected_year=search_year,
        selected_source=source,
        search_query=keyword,
        page_title="搜索",
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
        f"<div class='sync-item'><strong>来源级别</strong><span>{escape(source_trust_label(item.source))}</span></div>"
        f"<div class='sync-item'><strong>年份</strong><span>{item.year} 年</span></div>"
        f"<div class='sync-item'><strong>来源域名</strong><span>{escape(_source_hostname(item.link))}</span></div>"
        "</div>"
        "<div class='actions'>"
        f"<a class='ghost-link' href='{escape(item.link)}' target='_blank' rel='noreferrer'>查看原文</a>"
        f"<a class='ghost-link' href='{_build_href(f'/year/{item.year}', source=item.source)}'>查看同年同来源</a>"
        "</div>"
        f"<div class='notice'><strong>摘要：</strong>{escape(item.summary or '暂无摘要')}</div>"
        f"<div class='notice'><strong>可信说明：</strong>{escape(source_trust_note(item.source))}</div>"
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
        active_tab="archive",
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
    side_html = (
        "<section class='panel'>"
        "<div class='panel-head'><div><h2>状态说明</h2><div class='panel-subtitle'>同步页只保留任务状态和告警，不再展示来源覆盖。</div></div></div>"
        "<div class='notice compact'><strong>当前用途：</strong>看任务是否在跑、最近一次结果、以及来源异常告警。</div>"
        "</section>"
    )

    return _render_layout(
        active_tab="status",
        hero_title="同步状态",
        hero_text="同步状态页只负责任务状态与异常告警，不承担来源覆盖和专题展示。",
        stats=[
            ("当前状态", "进行中" if task_status["in_progress"] else "空闲"),
            ("最近同步", last_sync_at),
            ("数据库总条数", str(count_news_records())),
            ("已收录条数", str(len(recent_items))),
        ],
        main_html=main_html,
        side_html=side_html,
        year_counts=year_counts,
        source_counts=source_counts,
        current_year=current_year,
        page_title="同步状态",
    )
