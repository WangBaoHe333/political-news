"""时政资料库 Web 首页。"""

from datetime import datetime
from html import escape
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.ai_summary import generate_questions, generate_summary
from app.config import get_settings
from app.html_render import render_news, render_questions, render_summary, render_today_news
from app.news_data import group_by_month, latest_news_date, news_as_dict, query_news, today_news, yesterday_news
from app.sync_service import get_app_state, get_sync_status

router = APIRouter(tags=["页面"])


@router.get("/", response_class=HTMLResponse)
async def read_news(
    year: Optional[int] = Query(default=None),
    sync_status: str = Query(default=""),
):
    news_items, years = query_news(year=year)
    cfg = get_settings()
    ai_enabled = cfg.ai_enabled
    ai_status_notice = ""
    if not ai_enabled:
        ai_status_notice = (
            '<div class="ai-notice"><strong>提示：</strong>未检测到有效的OpenAI API Key，'
            "AI总结和题目生成功能使用基础模式。请配置OPENAI_API_KEY环境变量以启用完整AI功能。</div>"
        )
    news_dicts = news_as_dict(news_items)
    grouped = group_by_month(news_items)
    summary_lines = generate_summary(news_dicts)
    questions = generate_questions(news_dicts)
    today_items, today_title = today_news(news_items)
    yesterday_items, yesterday_title = yesterday_news(news_items)
    last_sync_at = get_app_state("last_sync_at", "尚未同步")
    last_sync_result = sync_status or get_app_state("last_sync_result", "")
    latest_published_at = latest_news_date(news_items)
    task_status = get_sync_status()

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
        .ai-notice {{
          margin-top: 16px;
          padding: 12px 14px;
          border-radius: 14px;
          border: 1px solid #c9b8a8;
          background: #fffaf5;
          font-size: 14px;
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
          {ai_status_notice}
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
            {render_today_news(today_items, today_title)}
          </div>
          <div class="panel" id="yesterday-news">
            {render_today_news(yesterday_items, yesterday_title)}
          </div>
          <div class="panel">
            <h2>AI 总结</h2>
            <ul>{render_summary(summary_lines)}</ul>
          </div>
        </section>

        <section class="grid">
          <div class="panel">
            <h2>按月归档</h2>
            {render_news(grouped)}
          </div>
          <div style="display: grid; gap: 20px;">
            <aside class="panel">
              <h2>公考风格练习题</h2>
              {render_questions(questions)}
            </aside>
          </div>
        </section>
      </main>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)
