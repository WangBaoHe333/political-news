import logging
import os
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.ai_summary import generate_questions, generate_summary
from app.database import SessionLocal, init_db
from app.fetch_news import fetch_news, save_news_to_db
from app.models import AppState, News
from app.tasks import setup_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Political News")
AUTO_SYNC_ON_STARTUP = os.getenv("AUTO_SYNC_ON_STARTUP", "0").lower() in {"1", "true", "yes", "on"}
SYNC_LOCK = threading.Lock()


def fetch_and_save_news(year=None, months=12, max_pages=None, max_items=None, start_date=None, end_date=None, progress_callback=None):
    news_items = fetch_news(
        year=year,
        months=months,
        max_pages=max_pages,
        max_items=max_items,
        start_date=start_date,
        end_date=end_date,
        progress_callback=progress_callback,
    )
    saved_count = save_news_to_db(news_items)
    _set_app_state("last_sync_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    _set_app_state("last_sync_result", f"本次抓取 {len(news_items)} 条，新增 {saved_count} 条。")
    logger.info("Fetched %s items, saved %s new records", len(news_items), saved_count)
    return {"fetched": len(news_items), "saved": saved_count}


def _query_news(year=None):
    db = SessionLocal()
    try:
        query = db.query(News)
        if year:
            query = query.filter(News.year == year)
        else:
            start_date = datetime.utcnow() - timedelta(days=365)
            query = query.filter(News.published_at >= start_date)

        news_items = query.order_by(News.published_at.desc()).all()
        years = [value[0] for value in db.query(News.year).distinct().order_by(News.year.desc()).all()]
        return news_items, years
    finally:
        db.close()


def _get_app_state(key, default=""):
    db = SessionLocal()
    try:
        state = db.query(AppState).filter(AppState.key == key).first()
        return state.value if state else default
    finally:
        db.close()


def _set_app_state(key, value):
    db = SessionLocal()
    try:
        state = db.query(AppState).filter(AppState.key == key).first()
        if state:
            state.value = value
        else:
            db.add(AppState(key=key, value=value))
        db.commit()
    finally:
        db.close()


def _get_sync_status():
    return {
        "in_progress": _get_app_state("sync_in_progress", "0") == "1",
        "scope": _get_app_state("sync_scope", ""),
        "message": _get_app_state("sync_message", ""),
        "started_at": _get_app_state("sync_started_at", ""),
        "finished_at": _get_app_state("sync_finished_at", ""),
        "last_result": _get_app_state("last_sync_result", ""),
    }


def _reset_stale_sync_state():
    if _get_app_state("sync_in_progress", "0") != "1":
        return

    _set_app_state("sync_in_progress", "0")
    _set_app_state("sync_finished_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))

    existing_message = _get_app_state("sync_message", "")
    if existing_message:
        _set_app_state("sync_message", f"检测到服务重启，已重置上一次未完成的后台任务。上次状态：{existing_message}")


def _run_background_sync(scope_label, year=None, months=12, max_pages=None, max_items=None):
    with SYNC_LOCK:
        _set_app_state("sync_in_progress", "1")
        _set_app_state("sync_scope", scope_label)
        _set_app_state("sync_started_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        _set_app_state("sync_finished_at", "")
        _set_app_state("sync_message", f"{scope_label}后台回填已启动，请稍候刷新进度。")
        try:
            result = fetch_and_save_news(year=year, months=months, max_pages=max_pages, max_items=max_items)
            _set_app_state("sync_message", f"{scope_label}后台回填完成：抓取 {result['fetched']} 条，新增 {result['saved']} 条。")
        except Exception as exc:
            logger.exception("Background sync failed: %s", exc)
            _set_app_state("sync_message", f"{scope_label}后台回填失败：{exc}")
        finally:
            _set_app_state("sync_finished_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            _set_app_state("sync_in_progress", "0")


def _month_batches(total_months, batch_size=3):
    now = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    batches = []
    remaining = total_months
    current_end = now

    while remaining > 0 and current_end.year >= 2000:
        current_batch = min(batch_size, remaining)

        if current_end.month == 1:
            batch_start_month = current_end.replace(year=current_end.year - (current_batch - 1), month=1, day=1)
        else:
            month_index = current_end.year * 12 + current_end.month - 1
            start_index = month_index - (current_batch - 1)
            start_year = start_index // 12
            start_month = start_index % 12 + 1
            batch_start_month = datetime(start_year, start_month, 1)

        if current_end.month == 12:
            next_month = current_end.replace(year=current_end.year + 1, month=1, day=1)
        else:
            next_month = current_end.replace(month=current_end.month + 1, day=1)

        start = batch_start_month
        end = next_month - timedelta(seconds=1)
        batches.append((start, end, current_batch))
        remaining -= current_batch

        if batch_start_month.month == 1:
            current_end = batch_start_month.replace(year=batch_start_month.year - 1, month=12, day=1)
        else:
            current_end = batch_start_month.replace(month=batch_start_month.month - 1, day=1)

    return batches


def _run_batched_backfill(scope_label, total_months, batch_size=3, max_items=150):
    with SYNC_LOCK:
        _set_app_state("sync_in_progress", "1")
        _set_app_state("sync_scope", scope_label)
        _set_app_state("sync_started_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        _set_app_state("sync_finished_at", "")
        completed = 0
        total_fetched = 0
        total_saved = 0
        try:
            for start, end, months in _month_batches(total_months, batch_size=batch_size):
                label = f"{start.strftime('%Y-%m')} 至 {end.strftime('%Y-%m')}"
                _set_app_state("sync_message", f"{scope_label}后台回填进行中：正在处理 {label}。")
                def on_progress(info):
                    if info.get("stage") == "archive_page":
                        page = info.get("page")
                        matched = info.get("matched")
                        added_total = info.get("added_total")
                        note = info.get("note", "")
                        suffix = f"，备注：{note}" if note else ""
                        _set_app_state(
                            "sync_message",
                            f"{scope_label}后台回填进行中：{label}，历史页 home_{page}.htm 命中 {matched} 条，当前累计待写入 {added_total} 条{suffix}。",
                        )
                    elif info.get("stage") == "json":
                        _set_app_state(
                            "sync_message",
                            f"{scope_label}后台回填进行中：{label}，近期 JSON 命中 {info.get('collected', 0)} 条。",
                        )

                result = fetch_and_save_news(
                    start_date=start,
                    end_date=end,
                    max_items=max_items,
                    progress_callback=on_progress,
                )
                completed += months
                total_fetched += result["fetched"]
                total_saved += result["saved"]
                _set_app_state(
                    "sync_message",
                    f"{scope_label}后台回填进行中：已完成 {completed}/{total_months} 个月，累计抓取 {total_fetched} 条，新增 {total_saved} 条。",
                )

            final_message = f"{scope_label}后台回填完成：累计抓取 {total_fetched} 条，新增 {total_saved} 条。"
            _set_app_state("sync_message", final_message)
            _set_app_state("last_sync_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            _set_app_state("last_sync_result", final_message)
        except Exception as exc:
            logger.exception("Batched backfill failed: %s", exc)
            _set_app_state("sync_message", f"{scope_label}后台回填失败：{exc}")
        finally:
            _set_app_state("sync_finished_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            _set_app_state("sync_in_progress", "0")


def _start_background_sync(scope_label, year=None, months=12, max_pages=None, max_items=None):
    if _get_app_state("sync_in_progress", "0") == "1":
        return False

    worker = threading.Thread(
        target=_run_background_sync,
        kwargs={
            "scope_label": scope_label,
            "year": year,
            "months": months,
            "max_pages": max_pages,
            "max_items": max_items,
        },
        daemon=True,
    )
    worker.start()
    return True


def _start_batched_backfill(scope_label, total_months, batch_size=3, max_items=150):
    if _get_app_state("sync_in_progress", "0") == "1":
        return False

    worker = threading.Thread(
        target=_run_batched_backfill,
        kwargs={
            "scope_label": scope_label,
            "total_months": total_months,
            "batch_size": batch_size,
            "max_items": max_items,
        },
        daemon=True,
    )
    worker.start()
    return True


def _as_dict(news_items):
    return [
        {
            "id": item.id,
            "source": item.source,
            "category": item.category,
            "title": item.title,
            "link": item.link,
            "summary": item.summary,
            "content": item.content,
            "published": item.published,
            "published_at": item.published_at,
            "year": item.year,
            "month": item.month,
        }
        for item in news_items
    ]


def _group_by_month(news_items):
    groups = OrderedDict()
    for item in news_items:
        key = item.published_at.strftime("%Y年%m月")
        groups.setdefault(key, []).append(item)
    return groups


def _latest_news_date(news_items):
    if not news_items:
        return None
    return max(item.published_at for item in news_items)


def _today_news(news_items):
    today = datetime.utcnow().date()
    today_items = [item for item in news_items if item.published_at.date() == today]
    return today_items[:8], f"今日时政（{today.strftime('%Y-%m-%d')}）"


def _yesterday_news(news_items):
    yesterday = datetime.utcnow().date() - timedelta(days=1)
    yesterday_items = [item for item in news_items if item.published_at.date() == yesterday]
    return yesterday_items[:8], f"昨日时政（{yesterday.strftime('%Y-%m-%d')}）"


def _latest_news(news_items):
    """保留原功能：返回最新日期的新闻"""
    latest_date = _latest_news_date(news_items)
    if not latest_date:
        return [], "最新时政"

    latest_items = [item for item in news_items if item.published_at.date() == latest_date.date()]
    return latest_items[:8], f"最新时政（{latest_date.strftime('%Y-%m-%d')}）"


def _render_summary(items):
    return "".join(f"<li>{escape(line)}</li>" for line in items)


def _render_questions(questions):
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


def _render_news(groups):
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


def _render_today_news(items, section_title):
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


@app.get("/", response_class=HTMLResponse)
async def read_news(
    year: Optional[int] = Query(default=None),
    sync_status: str = Query(default=""),
):
    news_items, years = _query_news(year=year)
    # 检查AI功能状态
    openai_key = os.getenv("OPENAI_API_KEY", "")
    ai_enabled = bool(openai_key and openai_key.strip() and openai_key != "your_openai_api_key_here")
    ai_status_notice = ""
    if not ai_enabled:
        ai_status_notice = '<div class="ai-notice"><strong>提示：</strong>未检测到有效的OpenAI API Key，AI总结和题目生成功能使用基础模式。请配置OPENAI_API_KEY环境变量以启用完整AI功能。</div>'
    news_dicts = _as_dict(news_items)
    grouped = _group_by_month(news_items)
    summary_lines = generate_summary(news_dicts)
    questions = generate_questions(news_dicts)
    today_items, today_title = _today_news(news_items)
    yesterday_items, yesterday_title = _yesterday_news(news_items)
    last_sync_at = _get_app_state("last_sync_at", "尚未同步")
    last_sync_result = sync_status or _get_app_state("last_sync_result", "")
    latest_published_at = _latest_news_date(news_items)
    task_status = _get_sync_status()

    selected_year = str(year) if year else "近一年"
    range_label = "近一年（参照公务员时政常见考查周期）" if not year else f"{year}年"
    year_options = ['<option value="">近一年</option>']
    for value in years:
        selected = " selected" if year == value else ""
        year_options.append(f'<option value="{value}"{selected}>{value}年</option>')

    empty_state = ""
    if not news_items:
        if year:
            empty_message = f"当前数据源暂无 {year} 年时政内容，请切换到近一年或已有年份。"
        else:
            empty_message = "当前近一年范围内还没有可展示的时政数据，请先点击上方同步按钮。"
        empty_state = (
            '<div class="empty-state">'
            f"{escape(empty_message)}"
            "</div>"
        )

    sync_notice = ""
    if last_sync_result:
        sync_notice = f'<div class="sync-notice"><strong>最近同步：</strong>{escape(last_sync_result)}</div>'

    sync_task_notice = ""
    if task_status["message"]:
        sync_task_notice = (
            f'<div class="sync-notice"><strong>后台任务：</strong>{escape(task_status["message"])}'
            f' 当前状态：{"进行中" if task_status["in_progress"] else "空闲"}。</div>'
        )

    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>时政资料库</title>
      <style>
        :root {{
          --bg: #f4f1ea;
          --panel: #fffdf8;
          --ink: #1d2a33;
          --accent: #9f2b25;
          --accent-soft: #e7c8b7;
          --line: #d9d1c7;
        }}
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          font-family: "Noto Serif SC", "Songti SC", serif;
          color: var(--ink);
          background:
            radial-gradient(circle at top left, rgba(159, 43, 37, 0.12), transparent 30%),
            linear-gradient(180deg, #f7f2ea 0%, var(--bg) 100%);
        }}
        a {{ color: var(--accent); text-decoration: none; }}
        .shell {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 64px; }}
        .hero {{
          padding: 28px;
          border: 1px solid var(--line);
          background: linear-gradient(135deg, rgba(255,255,255,0.92), rgba(247,239,229,0.95));
          border-radius: 24px;
          box-shadow: 0 18px 40px rgba(61, 44, 35, 0.08);
        }}
        .hero h1 {{ margin: 0 0 8px; font-size: 40px; }}
        .hero p {{ margin: 0; line-height: 1.7; max-width: 720px; }}
        .toolbar {{
          margin-top: 20px;
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          align-items: center;
        }}
        .toolbar .sync-form {{
          display: inline-flex;
        }}
        .toolbar form,
        .toolbar .actions {{
          display: flex;
          gap: 12px;
          align-items: center;
          flex-wrap: wrap;
        }}
        select, button, .action-link {{
          border-radius: 999px;
          border: 1px solid var(--line);
          background: var(--panel);
          padding: 10px 16px;
          color: var(--ink);
          font-size: 15px;
        }}
        button, .action-link {{
          cursor: pointer;
          background: var(--accent);
          color: white;
          border-color: transparent;
        }}
        .grid {{
          margin-top: 24px;
          display: grid;
          grid-template-columns: 1.25fr 0.75fr;
          gap: 20px;
        }}
        .panel {{
          background: var(--panel);
          border: 1px solid var(--line);
          border-radius: 22px;
          padding: 22px;
          box-shadow: 0 12px 28px rgba(61, 44, 35, 0.05);
        }}
        .top-panels {{
          margin-top: 20px;
          display: grid;
          grid-template-columns: 0.9fr 0.9fr 1.2fr;
          gap: 20px;
        }}
        .panel h2 {{ margin-top: 0; margin-bottom: 12px; }}
        .month-block + .month-block {{
          margin-top: 22px;
          padding-top: 22px;
          border-top: 1px dashed var(--line);
        }}
        .month-title {{
          display: inline-block;
          margin-bottom: 14px;
          padding: 6px 12px;
          border-radius: 999px;
          background: var(--accent-soft);
          color: #63211c;
          font-weight: 700;
        }}
        .news-card + .news-card {{
          margin-top: 14px;
          padding-top: 14px;
          border-top: 1px solid rgba(217, 209, 199, 0.65);
        }}
        .news-meta {{
          font-size: 13px;
          color: #6b6f73;
          margin-bottom: 6px;
        }}
        .news-card h4 {{
          margin: 0 0 8px;
          font-size: 18px;
          line-height: 1.5;
        }}
        .news-card p,
        .question-card p,
        .panel li {{
          line-height: 1.75;
        }}
        .question-card + .question-card {{
          margin-top: 18px;
          padding-top: 18px;
          border-top: 1px solid rgba(217, 209, 199, 0.65);
        }}
        .question-type {{
          color: var(--accent);
          font-size: 13px;
          font-weight: 700;
          letter-spacing: 0.06em;
          text-transform: uppercase;
        }}
        .empty-state {{
          margin-top: 18px;
          padding: 18px;
          border-radius: 16px;
          background: #fff7f0;
          border: 1px dashed #d2ad9c;
        }}
        .facts {{
          display: grid;
          gap: 10px;
          margin-top: 16px;
        }}
        .fact {{
          padding: 12px 14px;
          border-radius: 14px;
          background: rgba(159, 43, 37, 0.06);
        }}
        .sync-notice {{
          margin-top: 16px;
          padding: 12px 14px;
          border-radius: 14px;
          border: 1px solid #d9c2b7;
          background: #fff8f2;
        }}
        @media (max-width: 960px) {{
          .top-panels {{ grid-template-columns: 1fr; }}
          .grid {{ grid-template-columns: 1fr; }}
          .hero h1 {{ font-size: 32px; }}
        }}
      </style>
    </head>
    <body>
      <main class="shell">
        <section class="hero">
          <h1>时政资料库</h1>
          <p>默认展示近一年的时政材料，可切换到具体年份查看，并按月份自动归档。右侧会基于当前筛选范围，生成只依赖原始文本的总结与题目。</p>
          <div class="toolbar">
            <form method="get" action="/">
              <label for="year">查看范围</label>
              <select id="year" name="year">{''.join(year_options)}</select>
              <button type="submit">切换</button>
            </form>
            <div class="actions">
              <form class="sync-form" method="get" action="/sync-view">
                <input type="hidden" name="months" value="12" />
                <button type="submit">后台同步近一年</button>
              </form>
              <form class="sync-form" method="get" action="/sync-view">
                <input type="hidden" name="months" value="24" />
                <button type="submit">后台同步近两年</button>
              </form>
              <form class="sync-form" method="get" action="/backfill-view">
                <input type="hidden" name="months" value="24" />
                <button type="submit">分批回填近两年</button>
              </form>
              <form class="sync-form" method="get" action="/sync-view">
                <input type="hidden" name="year" value="{datetime.utcnow().year}" />
                <button type="submit">后台同步本年</button>
              </form>
              <a class="action-link" href="#today-news">查看今日时政</a>
              <a class="action-link" href="/sync-status">查看同步状态</a>
            </div>
          </div>
          <div class="facts">
            <div class="fact"><strong>当前视图：</strong>{selected_year}</div>
            <div class="fact"><strong>考公参考范围：</strong>{range_label}</div>
            <div class="fact"><strong>数据最新发布日期：</strong>{escape(latest_published_at.strftime("%Y-%m-%d") if latest_published_at else "暂无数据")}</div>
            <div class="fact"><strong>最近同步时间：</strong>{escape(last_sync_at)}（服务器记录）</div>
          </div>
          {sync_notice}
          {sync_task_notice}
        </section>

        {empty_state}

        <section class="top-panels">
          <div class="panel" id="today-news">
            {_render_today_news(today_items, today_title)}
          </div>
          <div class="panel" id="yesterday-news">
            {_render_today_news(yesterday_items, yesterday_title)}
          </div>
          <div class="panel">
            <h2>AI 总结</h2>
            <ul>{_render_summary(summary_lines)}</ul>
          </div>
        </section>

        <section class="grid">
          <div class="panel">
            <h2>按月归档</h2>
            {_render_news(grouped)}
          </div>
          <div style="display: grid; gap: 20px;">
            <aside class="panel">
              <h2>公考风格练习题</h2>
              {_render_questions(questions)}
            </aside>
          </div>
        </section>
      </main>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


@app.get("/sync")
async def sync_news(
    year: Optional[int] = Query(default=None),
    months: int = Query(default=12, ge=1, le=36),
    max_pages: Optional[int] = Query(default=None, ge=1, le=500),
    max_items: Optional[int] = Query(default=None, ge=1, le=1000),
):
    result = fetch_and_save_news(year=year, months=months, max_pages=max_pages, max_items=max_items)
    return JSONResponse(result)


@app.get("/sync-view")
async def sync_view(
    year: Optional[int] = Query(default=None),
    months: int = Query(default=12, ge=1, le=36),
    max_pages: Optional[int] = Query(default=None, ge=1, le=500),
    max_items: Optional[int] = Query(default=None, ge=1, le=1000),
):
    scope = f"{year}年" if year else f"近{months}个月"
    started = _start_background_sync(scope, year=year, months=months, max_pages=max_pages, max_items=max_items)
    if started:
        status = f"{scope}后台同步已启动，请稍后刷新页面查看结果。"
    else:
        status = "已有后台同步任务在运行，请稍后刷新查看。"
    encoded_status = quote(status)
    redirect_url = f"/?sync_status={encoded_status}"
    if year:
        redirect_url = f"/?year={year}&sync_status={encoded_status}"
    return RedirectResponse(url=redirect_url, status_code=303)


@app.get("/sync-status")
async def sync_status():
    return JSONResponse(_get_sync_status())


@app.get("/backfill-view")
async def backfill_view(
    months: int = Query(default=24, ge=1, le=36),
    batch_size: int = Query(default=3, ge=1, le=6),
    max_items: int = Query(default=150, ge=20, le=400),
):
    scope = f"近{months}个月分批回填"
    started = _start_batched_backfill(scope, total_months=months, batch_size=batch_size, max_items=max_items)
    if started:
        status = f"{scope}已启动，每批 {batch_size} 个月。请稍后刷新页面查看进度。"
    else:
        status = "已有后台同步任务在运行，请稍后刷新查看。"
    encoded_status = quote(status)
    return RedirectResponse(url=f"/?sync_status={encoded_status}", status_code=303)


@app.get("/api/news")
async def api_news(year: Optional[int] = Query(default=None)):
    news_items, years = _query_news(year=year)
    data = _as_dict(news_items)
    for item in data:
        item["published_at"] = item["published_at"].isoformat()
    return JSONResponse({"years": years, "items": data})


@app.get("/api/news/today")
async def api_news_today():
    news_items, _ = _query_news(year=None)
    today_items, today_title = _today_news(news_items)
    data = _as_dict(today_items)
    for item in data:
        item["published_at"] = item["published_at"].isoformat()
    return JSONResponse({"title": today_title, "items": data})


@app.get("/api/news/yesterday")
async def api_news_yesterday():
    news_items, _ = _query_news(year=None)
    yesterday_items, yesterday_title = _yesterday_news(news_items)
    data = _as_dict(yesterday_items)
    for item in data:
        item["published_at"] = item["published_at"].isoformat()
    return JSONResponse({"title": yesterday_title, "items": data})


@app.get("/api/news/grouped-by-month")
async def api_news_grouped_by_month(year: Optional[int] = Query(default=None)):
    news_items, years = _query_news(year=year)
    grouped = _group_by_month(news_items)
    result = {}
    for month_label, items in grouped.items():
        data = _as_dict(items)
        for item in data:
            item["published_at"] = item["published_at"].isoformat()
        result[month_label] = data
    return JSONResponse({"years": years, "grouped_by_month": result})


@app.get("/api/news/past-two-years")
async def api_news_past_two_years():
    # 获取过去两年的数据（当前年和前一年）
    current_year = datetime.utcnow().year
    all_items = []
    for year in [current_year, current_year - 1]:
        news_items, _ = _query_news(year=year)
        all_items.extend(news_items)

    # 按时间倒序排序
    all_items.sort(key=lambda x: x.published_at, reverse=True)

    data = _as_dict(all_items)
    for item in data:
        item["published_at"] = item["published_at"].isoformat()

    # 按月份分组
    grouped = _group_by_month(all_items)
    grouped_result = {}
    for month_label, items in grouped.items():
        month_data = _as_dict(items)
        for item in month_data:
            item["published_at"] = item["published_at"].isoformat()
        grouped_result[month_label] = month_data

    return JSONResponse({
        "title": f"过去两年时政内容 ({current_year-1}-{current_year})",
        "total_items": len(data),
        "items": data,
        "grouped_by_month": grouped_result
    })


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.on_event("startup")
def bootstrap():
    init_db()
    _reset_stale_sync_state()
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("定时任务调度器已启动")
    if not AUTO_SYNC_ON_STARTUP:
        logger.info("Startup auto sync is disabled; serving cached database content only.")
        return

    try:
        fetch_and_save_news(months=3, max_items=120)
    except Exception as exc:
        logger.exception("Startup bootstrap failed: %s", exc)
