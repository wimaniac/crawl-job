"""
Pipeline: đọc job ĐÃ PHÂN TÍCH (có match_score), đạt ngưỡng, CHƯA từng được
gửi email → gộp thành 1 email tổng hợp → gửi → đánh dấu đã gửi.

Chỉ đánh dấu "đã gửi" khi send_email() thực sự thành công — nếu SMTP lỗi,
job vẫn giữ nguyên notified_at = NULL để lần chạy sau thử gửi lại.

Chạy:
  python -m src.notification.run_notify
  python -m src.notification.run_notify --min-score 70
  python -m src.notification.run_notify --limit 20
  python -m src.notification.run_notify --dry-run   # không gửi thật, chỉ ghi ra file HTML để xem trước
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database.connection import DatabaseConnection, close_pool
from src.notification.email_notifier import format_jobs_to_html, send_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_MIN_SCORE = int(os.getenv("NOTIFY_MIN_SCORE", "70"))


async def _ensure_notified_column() -> None:
    """Thêm cột notified_at nếu chưa có — an toàn khi gọi nhiều lần (IF NOT EXISTS)."""
    async with DatabaseConnection() as conn:
        await conn.execute(
            "ALTER TABLE job_listings "
            "ADD COLUMN IF NOT EXISTS notified_at TIMESTAMP WITH TIME ZONE"
        )


async def get_jobs_for_notification(
    pool: asyncpg.Pool, min_score: int, limit: int | None
) -> list[dict]:
    """Job đã phân tích, đạt ngưỡng match_score, CHƯA từng gửi email."""
    sql = """
        SELECT id, job_title, company_name, location, salary_range,
               job_url, match_score, ai_analysis
        FROM job_listings
        WHERE match_score IS NOT NULL
          AND match_score >= $1
          AND notified_at IS NULL
        ORDER BY match_score DESC
    """
    params: list = [min_score]
    if limit:
        sql += " LIMIT $2"
        params.append(limit)

    async with DatabaseConnection() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def mark_jobs_notified(pool: asyncpg.Pool, job_ids: list[int]) -> None:
    if not job_ids:
        return
    async with DatabaseConnection() as conn:
        await conn.execute(
            "UPDATE job_listings SET notified_at = NOW() WHERE id = ANY($1::int[])",
            job_ids,
        )


async def run_notify(
    min_score: int = DEFAULT_MIN_SCORE,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    logger.info("=== Bắt đầu pipeline gửi email thông báo job ===")
    stats = {"found": 0, "sent": False, "marked": 0}
    pool = None # Sẽ được quản lý bởi DatabaseConnection

    try:
        await _ensure_notified_column()

        jobs = await get_jobs_for_notification(None, min_score, limit)
        stats["found"] = len(jobs)

        if not jobs:
            logger.info(
                f"Không có job mới nào đạt ngưỡng match_score >= {min_score} "
                "và chưa từng được gửi."
            )
            return stats

        logger.info(f"Tìm thấy {len(jobs)} job đạt ngưỡng, chuẩn bị gửi email...")
        html_content = format_jobs_to_html(jobs)

        if dry_run:
            out_path = Path("dry_run_email.html")
            out_path.write_text(html_content, encoding="utf-8")
            logger.info(
                f"[DRY RUN] Không gửi email thật, không đánh dấu đã gửi. "
                f"Đã ghi nội dung ra: {out_path.resolve()}"
            )
            return stats

        subject = (
            f"Báo cáo việc làm hàng ngày - {datetime.now().strftime('%d/%m/%Y')} "
            f"({len(jobs)} job phù hợp)"
        )
        ok = send_email(subject, html_content)
        stats["sent"] = ok

        if ok:
            job_ids = [j["id"] for j in jobs]
            await mark_jobs_notified(None, job_ids) # pool không còn được truyền trực tiếp
            stats["marked"] = len(job_ids)
            logger.info(f"Đã đánh dấu {len(job_ids)} job là đã gửi (notified_at).")
        else:
            logger.warning(
                "Gửi email thất bại — KHÔNG đánh dấu job đã gửi, "
                "lần chạy sau sẽ tự thử lại các job này."
            )

        return stats
    finally:
        await close_pool()


def main():
    parser = argparse.ArgumentParser(description="Gửi email thông báo job phù hợp")
    parser.add_argument(
        "--min-score", type=int, default=DEFAULT_MIN_SCORE,
        help=f"Ngưỡng match_score tối thiểu để gửi (mặc định {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument("--limit", type=int, default=None, help="Giới hạn số job trong email")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Không gửi email thật, chỉ ghi nội dung ra dry_run_email.html để xem trước",
    )
    args = parser.parse_args()

    stats = asyncio.run(
        run_notify(min_score=args.min_score, limit=args.limit, dry_run=args.dry_run)
    )
    logger.info(f"=== Xong: {stats} ===")


if __name__ == "__main__":
    main()