"""抓取入库与后台同步任务状态。"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.database import SessionLocal
from app.fetch_news import fetch_news, save_news_to_db
from app.models import AppState

logger = logging.getLogger(__name__)

SYNC_LOCK = threading.Lock()


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
    set_app_state("last_sync_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
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
    return {
        "in_progress": get_app_state("sync_in_progress", "0") == "1",
        "scope": get_app_state("sync_scope", ""),
        "message": get_app_state("sync_message", ""),
        "started_at": get_app_state("sync_started_at", ""),
        "finished_at": get_app_state("sync_finished_at", ""),
        "last_sync_at": get_app_state("last_sync_at", ""),
        "last_result": get_app_state("last_sync_result", ""),
    }


def reset_stale_sync_state() -> None:
    if get_app_state("sync_in_progress", "0") != "1":
        return

    set_app_state("sync_in_progress", "0")
    set_app_state("sync_finished_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))

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
    with SYNC_LOCK:
        set_app_state("sync_in_progress", "1")
        set_app_state("sync_scope", scope_label)
        set_app_state("sync_started_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        set_app_state("sync_finished_at", "")
        set_app_state("sync_message", f"{scope_label}后台回填已启动，请稍候刷新进度。")
        try:
            result = fetch_and_save_news(
                year=year, months=months, max_pages=max_pages, max_items=max_items
            )
            set_app_state(
                "sync_message",
                f"{scope_label}后台回填完成：抓取 {result['fetched']} 条，新增 {result['saved']} 条。",
            )
        except Exception as exc:
            logger.exception("Background sync failed: %s", exc)
            set_app_state("sync_message", f"{scope_label}后台回填失败：{exc}")
        finally:
            set_app_state("sync_finished_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            set_app_state("sync_in_progress", "0")


def month_batches(total_months: int, batch_size: int = 3) -> List[Tuple[datetime, datetime, int]]:
    now = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
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
    with SYNC_LOCK:
        set_app_state("sync_in_progress", "1")
        set_app_state("sync_scope", scope_label)
        set_app_state("sync_started_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        set_app_state("sync_finished_at", "")
        completed = 0
        total_fetched = 0
        total_saved = 0
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
            set_app_state("last_sync_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            set_app_state("last_sync_result", final_message)
        except Exception as exc:
            logger.exception("Batched backfill failed: %s", exc)
            set_app_state("sync_message", f"{scope_label}后台回填失败：{exc}")
        finally:
            set_app_state("sync_finished_at", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            set_app_state("sync_in_progress", "0")


def start_background_sync(
    scope_label: str,
    year: Optional[int] = None,
    months: int = 12,
    max_pages: Optional[int] = None,
    max_items: Optional[int] = None,
) -> bool:
    if get_app_state("sync_in_progress", "0") == "1":
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


def start_batched_backfill(
    scope_label: str, total_months: int, batch_size: int = 3, max_items: int = 150
) -> bool:
    if get_app_state("sync_in_progress", "0") == "1":
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
