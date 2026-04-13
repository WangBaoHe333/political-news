"""抓取入库与后台同步任务状态。"""

import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from app.database import SessionLocal
from app.fetch_news import fetch_news, save_news_to_db
from app.models import AppState, News

logger = logging.getLogger(__name__)

SYNC_LOCK = threading.Lock()
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _utc_now_str() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _parse_alerts(raw: str) -> List[str]:
    try:
        parsed = json.loads(raw or "[]")
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (TypeError, ValueError):
        pass
    return []


def _parse_json_state(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError):
        pass
    return {}


def _render_source_alert(info: Dict[str, Any]) -> Optional[str]:
    if info.get("stage") != "source_health":
        return None
    status = info.get("status")
    if status == "healthy":
        return None
    source = str(info.get("source") or "unknown")
    channel = str(info.get("channel") or "source")
    note = str(info.get("note") or "来源抓取异常")
    return f"{source}({channel}): {note}"


def _save_source_alerts(alerts: List[str]) -> None:
    unique_alerts = list(dict.fromkeys(alerts))
    set_app_state("source_alerts", json.dumps(unique_alerts, ensure_ascii=False))


def _update_source_health(events: List[Dict[str, Any]]) -> None:
    previous = _parse_json_state(get_app_state("source_health", "{}"))
    current = dict(previous)
    now_text = _utc_now_str()

    for event in events:
        source = str(event.get("source") or "").strip()
        if not source:
            continue

        status = str(event.get("status") or "unknown")
        note = str(event.get("note") or "")
        matched = int(event.get("matched") or 0)
        errors = int(event.get("errors") or 0)
        channel = str(event.get("channel") or "")

        previous_item = current.get(source) if isinstance(current.get(source), dict) else {}
        previous_failures = int(previous_item.get("consecutive_failures") or 0)
        consecutive_failures = 0 if status == "healthy" else previous_failures + 1

        current[source] = {
            "status": status,
            "note": note,
            "channel": channel,
            "matched": matched,
            "errors": errors,
            "consecutive_failures": consecutive_failures,
            "last_checked": now_text,
        }

    set_app_state("source_health", json.dumps(current, ensure_ascii=False))


def fetch_and_save_news(
    year: Optional[int] = None,
    months: int = 12,
    max_pages: Optional[int] = None,
    max_items: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, int]:
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
    set_app_state("last_sync_at", _utc_now_str())
    set_app_state("last_sync_result", f"本次抓取 {len(news_items)} 条，新增 {saved_count} 条。")
    logger.info("Fetched %s items, saved %s new records", len(news_items), saved_count)
    return {"fetched": len(news_items), "saved": saved_count}


def get_app_state(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        state = db.query(AppState).filter(AppState.key == key).first()
        return state.value if state else default
    finally:
        db.close()


def set_app_state(key: str, value: str) -> None:
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


def get_sync_status() -> Dict[str, Any]:
    source_health = _parse_json_state(get_app_state("source_health", "{}"))
    critical_sources = []
    for source, state in source_health.items():
        if not isinstance(state, dict):
            continue
        if int(state.get("consecutive_failures") or 0) >= 3:
            critical_sources.append(source)

    return {
        "in_progress": get_app_state("sync_in_progress", "0") == "1",
        "scope": get_app_state("sync_scope", ""),
        "message": get_app_state("sync_message", ""),
        "started_at": get_app_state("sync_started_at", ""),
        "finished_at": get_app_state("sync_finished_at", ""),
        "last_sync_at": get_app_state("last_sync_at", ""),
        "last_result": get_app_state("last_sync_result", ""),
        "source_alerts": _parse_alerts(get_app_state("source_alerts", "[]")),
        "source_health": source_health,
        "critical_sources": critical_sources,
    }


def has_recent_two_years_data(months: int = 24) -> bool:
    db = SessionLocal()
    try:
        total = db.query(News.id).count()
        if total == 0:
            return False

        oldest = db.query(News.published_at).order_by(News.published_at.asc()).first()
        latest = db.query(News.published_at).order_by(News.published_at.desc()).first()
        years = {value[0] for value in db.query(News.year).distinct().all()}

        if not oldest or not latest:
            return False

        now = datetime.now(LOCAL_TZ).replace(tzinfo=None)
        cutoff = now - timedelta(days=max(months, 1) * 30 - 14)
        required_years = {now.year, now.year - 1}

        return (
            oldest[0] <= cutoff
            and latest[0] >= now - timedelta(days=14)
            and required_years.issubset(years)
        )
    finally:
        db.close()


def reset_stale_sync_state() -> None:
    if get_app_state("sync_in_progress", "0") != "1":
        return

    set_app_state("sync_in_progress", "0")
    set_app_state("sync_finished_at", _utc_now_str())

    existing_message = get_app_state("sync_message", "")
    if existing_message:
        set_app_state(
            "sync_message",
            f"检测到服务重启，已重置上一次未完成的后台任务。上次状态：{existing_message}",
        )


def _run_background_sync(
    scope_label: str,
    year: Optional[int] = None,
    months: int = 12,
    max_pages: Optional[int] = None,
    max_items: Optional[int] = None,
) -> None:
    source_alerts: List[str] = []
    source_events: List[Dict[str, Any]] = []

    def on_progress(info: Dict[str, Any]) -> None:
        if info.get("stage") == "source_health":
            source_events.append(info)
        alert = _render_source_alert(info)
        if alert:
            source_alerts.append(alert)

    try:
        result = fetch_and_save_news(
            year=year,
            months=months,
            max_pages=max_pages,
            max_items=max_items,
            progress_callback=on_progress,
        )
        set_app_state(
            "sync_message",
            f"{scope_label}后台回填完成：抓取 {result['fetched']} 条，新增 {result['saved']} 条。",
        )
    except Exception as exc:
        logger.exception("Background sync failed: %s", exc)
        set_app_state("sync_message", f"{scope_label}后台回填失败：{exc}")
    finally:
        _update_source_health(source_events)
        _save_source_alerts(source_alerts)
        set_app_state("sync_finished_at", _utc_now_str())
        set_app_state("sync_in_progress", "0")
        SYNC_LOCK.release()


def month_batches(total_months: int, batch_size: int = 3) -> List[Tuple[datetime, datetime, int]]:
    now = datetime.now(LOCAL_TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    batches: List[Tuple[datetime, datetime, int]] = []
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


def _run_batched_backfill(
    scope_label: str, total_months: int, batch_size: int = 3, max_items: int = 150
) -> None:
    completed = 0
    total_fetched = 0
    total_saved = 0
    source_alerts: List[str] = []
    source_events: List[Dict[str, Any]] = []
    try:
        for start, end, months in month_batches(total_months, batch_size=batch_size):
            label = f"{start.strftime('%Y-%m')} 至 {end.strftime('%Y-%m')}"
            set_app_state("sync_message", f"{scope_label}后台回填进行中：正在处理 {label}。")

            def on_progress(info: Dict[str, Any]) -> None:
                if info.get("stage") == "archive_page":
                    page = info.get("page")
                    matched = info.get("matched")
                    added_total = info.get("added_total")
                    note = info.get("note", "")
                    suffix = f"，备注：{note}" if note else ""
                    set_app_state(
                        "sync_message",
                        f"{scope_label}后台回填进行中：{label}，历史页 home_{page}.htm 命中 {matched} 条，"
                        f"当前累计待写入 {added_total} 条{suffix}。",
                    )
                elif info.get("stage") == "json":
                    set_app_state(
                        "sync_message",
                        f"{scope_label}后台回填进行中：{label}，近期 JSON 命中 {info.get('collected', 0)} 条。",
                    )
                else:
                    if info.get("stage") == "source_health":
                        source_events.append(info)
                    alert = _render_source_alert(info)
                    if alert:
                        source_alerts.append(alert)

            result = fetch_and_save_news(
                start_date=start,
                end_date=end,
                max_items=max_items,
                progress_callback=on_progress,
            )
            completed += months
            total_fetched += result["fetched"]
            total_saved += result["saved"]
            set_app_state(
                "sync_message",
                f"{scope_label}后台回填进行中：已完成 {completed}/{total_months} 个月，"
                f"累计抓取 {total_fetched} 条，新增 {total_saved} 条。",
            )

        final_message = f"{scope_label}后台回填完成：累计抓取 {total_fetched} 条，新增 {total_saved} 条。"
        set_app_state("sync_message", final_message)
        set_app_state("last_sync_at", _utc_now_str())
        set_app_state("last_sync_result", final_message)
    except Exception as exc:
        logger.exception("Batched backfill failed: %s", exc)
        set_app_state("sync_message", f"{scope_label}后台回填失败：{exc}")
    finally:
        _update_source_health(source_events)
        _save_source_alerts(source_alerts)
        set_app_state("sync_finished_at", _utc_now_str())
        set_app_state("sync_in_progress", "0")
        SYNC_LOCK.release()


def run_sync_now(
    scope_label: str,
    year: Optional[int] = None,
    months: int = 12,
    max_pages: Optional[int] = None,
    max_items: Optional[int] = None,
) -> Optional[Dict[str, int]]:
    if not SYNC_LOCK.acquire(blocking=False):
        return None

    set_app_state("sync_in_progress", "1")
    set_app_state("sync_scope", scope_label)
    set_app_state("sync_started_at", _utc_now_str())
    set_app_state("sync_finished_at", "")
    set_app_state("sync_message", f"{scope_label}进行中，请稍候。")
    source_alerts: List[str] = []
    source_events: List[Dict[str, Any]] = []

    def on_progress(info: Dict[str, Any]) -> None:
        if info.get("stage") == "source_health":
            source_events.append(info)
        alert = _render_source_alert(info)
        if alert:
            source_alerts.append(alert)

    try:
        result = fetch_and_save_news(
            year=year,
            months=months,
            max_pages=max_pages,
            max_items=max_items,
            progress_callback=on_progress,
        )
        set_app_state(
            "sync_message",
            f"{scope_label}完成：抓取 {result['fetched']} 条，新增 {result['saved']} 条。",
        )
        return result
    except Exception as exc:
        logger.exception("Sync run failed: %s", exc)
        set_app_state("sync_message", f"{scope_label}失败：{exc}")
        raise
    finally:
        _update_source_health(source_events)
        _save_source_alerts(source_alerts)
        set_app_state("sync_finished_at", _utc_now_str())
        set_app_state("sync_in_progress", "0")
        SYNC_LOCK.release()


def run_scheduled_sync(months: int = 1, max_pages: int = 12, max_items: int = 80) -> Dict[str, int]:
    scope = "定时同步"
    result = run_sync_now(scope_label=scope, months=months, max_pages=max_pages, max_items=max_items)
    if result is None:
        logger.info("Scheduled sync skipped because another sync task is running.")
        return {"fetched": 0, "saved": 0}
    return result


def start_background_sync(
    scope_label: str,
    year: Optional[int] = None,
    months: int = 12,
    max_pages: Optional[int] = None,
    max_items: Optional[int] = None,
) -> bool:
    if not SYNC_LOCK.acquire(blocking=False):
        return False

    set_app_state("sync_in_progress", "1")
    set_app_state("sync_scope", scope_label)
    set_app_state("sync_started_at", _utc_now_str())
    set_app_state("sync_finished_at", "")
    set_app_state("sync_message", f"{scope_label}后台回填已启动，请稍候刷新进度。")

    try:
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
    except Exception:
        set_app_state("sync_in_progress", "0")
        set_app_state("sync_finished_at", _utc_now_str())
        set_app_state("sync_message", f"{scope_label}后台任务启动失败。")
        SYNC_LOCK.release()
        raise


def start_batched_backfill(
    scope_label: str, total_months: int, batch_size: int = 3, max_items: int = 150
) -> bool:
    if not SYNC_LOCK.acquire(blocking=False):
        return False

    set_app_state("sync_in_progress", "1")
    set_app_state("sync_scope", scope_label)
    set_app_state("sync_started_at", _utc_now_str())
    set_app_state("sync_finished_at", "")
    set_app_state("sync_message", f"{scope_label}后台回填已启动，请稍候刷新进度。")

    try:
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
    except Exception:
        set_app_state("sync_in_progress", "0")
        set_app_state("sync_finished_at", _utc_now_str())
        set_app_state("sync_message", f"{scope_label}后台任务启动失败。")
        SYNC_LOCK.release()
        raise
