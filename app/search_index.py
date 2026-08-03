"""SQLite FTS5 全文检索与中文分词（jieba）。

搜索流程：索引时用 jieba 对标题/摘要/正文分词后写入 news_fts（standalone FTS5 表），
查询时对用户输入同样分词并构造 MATCH 表达式，得到按相关性排序的 rowid 集合。
"""

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, List, Optional

import jieba
from sqlalchemy import text
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("Asia/Shanghai")

# 预热分词词典（首次调用有一次性开销，放在导入时提前做）
jieba.initialize()

# 参与检索的列（对应 news_fts 虚拟表的字段）
_SEARCH_COLUMNS = ("title", "summary", "content")

# 时政领域常见停用词：去掉过于宽泛、无筛选价值的词
_STOPWORDS = frozenset(
    """
    的 了 在 是 和 及 与 等 并 或 对 从 由 到 让 被 把 给 为 于 而 但 却 又 都 也 还 再 就 才 只 很 更 最
    中 上 下 前 后 内 外 时 个 种 项 这 那 一 二 三 十 百 千 万 亿 年 月 日
    今天 今年 明天 昨天 目前 当前 日前 近日 近年来 我国 中国 全国 国家 政府 记者 报道 新闻
    时政 重要 加强 推动 推进 坚持 全面 深化 加快 表示 强调 指出 要求 举行 召开 会议
    工作 发展 建设 进行 开展 完成 实现 提升 增强 保障 服务 管理 领域 部门 方面 情况 问题 水平
    机制 体系 政策 措施 制度 时代 特色 思想 精神 理念 目标 任务 内容 方法 需要 通过 按照
    切实 持续 不断 进一步 相关 有关 全面 有序 稳步 积极 深入 扎实 有效
    """.split()
)


def segment_text(text: Optional[str]) -> str:
    """jieba 分词，空格分隔，供 FTS5 索引与查询使用。"""
    if not text:
        return ""
    return " ".join(jieba.cut(text))


def _escape_fts_token(token: str) -> str:
    # FTS5 字符串内双引号需加倍转义
    return token.replace('"', '""')


def build_fts_query(query_text: str) -> str:
    """把用户输入转成 FTS5 MATCH 表达式。

    规则：每个分词都必须出现在 标题/摘要/正文 之一（AND 语义），
    列间用 OR 匹配，按相关性排序。
    """
    words = [w for w in jieba.cut(query_text.strip()) if w.strip()]
    if not words:
        return ""
    clauses = []
    for word in words:
        cols = " OR ".join(f'{col}:"{_escape_fts_token(word)}"' for col in _SEARCH_COLUMNS)
        clauses.append(f"({cols})")
    return " AND ".join(clauses)


def ensure_fts_table(conn: Any) -> None:
    """创建 FTS5 虚拟表（幂等）。"""
    conn.execute(
        text("CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(title, summary, content)")
    )


def index_news(conn: Any, news_id: int, title: str, summary: str, content: str) -> None:
    """把一条新闻写入 FTS 索引（先删后插，覆盖更新）。"""
    conn.execute(text("DELETE FROM news_fts WHERE rowid = :id"), {"id": news_id})
    conn.execute(
        text(
            "INSERT INTO news_fts(rowid, title, summary, content) "
            "VALUES (:id, :t, :s, :c)"
        ),
        {
            "id": news_id,
            "t": segment_text(title),
            "s": segment_text(summary or ""),
            "c": segment_text(content or ""),
        },
    )


def backfill_fts(conn: Any) -> None:
    """把已有 news 行补进 FTS 索引（索引行数与 news 一致则跳过）。"""
    news_rows = conn.execute(
        text("SELECT id, title, summary, content FROM news")
    ).fetchall()
    fts_count = conn.execute(text("SELECT COUNT(*) FROM news_fts")).scalar()
    if len(news_rows) == fts_count:
        return
    conn.execute(text("DELETE FROM news_fts"))
    for row in news_rows:
        index_news(conn, row[0], row[1], row[2], row[3])
    logger.info("FTS 索引回填完成，共 %d 条", len(news_rows))


def search_rowids(conn: Any, query_text: str, limit: int = 500) -> List[int]:
    """按 FTS5 相关性返回匹配的新闻 id 列表（未命中返回空列表）。"""
    fts_query = build_fts_query(query_text)
    if not fts_query:
        return []
    rows = conn.execute(
        text(
            "SELECT rowid FROM news_fts WHERE news_fts MATCH :q "
            "ORDER BY rank LIMIT :lim"
        ),
        {"q": fts_query, "lim": limit},
    ).fetchall()
    return [row[0] for row in rows]


def get_hot_keywords(limit: int = 20, days: int = 60) -> List[str]:
    """从近期文章标题提取高频关键词（热词）。"""
    from app.database import SessionLocal  # 延迟导入避免循环依赖

    db = SessionLocal()
    try:
        start = datetime.now(LOCAL_TZ).replace(tzinfo=None) - timedelta(days=days)
        rows = db.execute(
            text(
                "SELECT title FROM news WHERE published_at >= :start "
                "ORDER BY published_at DESC LIMIT 600"
            ),
            {"start": start},
        ).fetchall()
    finally:
        db.close()

    counter: Counter[str] = Counter()
    for (title,) in rows:
        for word in jieba.cut(title or ""):
            w = word.strip()
            if len(w) < 2 or w in _STOPWORDS:
                continue
            counter[w] += 1
    return [w for w, _ in counter.most_common(limit)]
