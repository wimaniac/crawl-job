"""
Pipeline: đọc job chưa phân tích từ PostgreSQL → LLM local → UPDATE match_score/ai_analysis.

Chạy:
  python -m src.analysis.run_analysis
  python -m src.analysis.run_analysis --limit 20
  python -m src.analysis.run_analysis --force-reindex
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Cho phép chạy trực tiếp file này
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.analyzer import (
    analyze_job_description,
    compose_job_text,
    setup_llm_and_query_engine,
)
from src.analysis.cv_indexer import get_cv_index
from src.database.connection import close_pool
from src.database.queries import get_unanalyzed_jobs, update_job_with_analysis

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Số lỗi LIÊN TIẾP tối đa trước khi dừng sớm cả batch. Lỗi liên tiếp nhiều
# thường là dấu hiệu Ollama đã chết/OOM hẳn (không phải do 1-2 JD khó) —
# cứ tiếp tục cày qua hàng trăm job còn lại chỉ tổ log toàn lỗi vô ích và
# tốn thời gian chờ timeout (request_timeout=180s) cho từng job.
MAX_CONSECUTIVE_FAILURES = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "5"))
# Số lần thử lại cho 1 job khi gặp lỗi (network hiccup, Ollama tạm không
# phản hồi...). KHÔNG nên đặt quá cao — nếu lỗi là do OOM/crash thật sự,
# retry ngay lập tức nhiều khả năng lại crash y hệt, chỉ tổ chờ lâu hơn.
JOB_RETRY_COUNT = int(os.getenv("JOB_RETRY_COUNT", "1"))
# Nghỉ giữa các job (giây) — giảm áp lực dồn dập lên Ollama, đặc biệt khi
# chạy inference trên CPU (không có GPU rảnh để "thở" giữa các request).
JOB_PACING_SECONDS = float(os.getenv("JOB_PACING_SECONDS", "0.5"))


def _analyze_with_retry(query_engine, jd_text: str, job_id, retries: int) -> dict | None:
    """Gọi analyze_job_description với retry giới hạn cho lỗi tạm thời."""
    for attempt in range(1, retries + 2):  # thử chính + `retries` lần retry
        try:
            result = analyze_job_description(query_engine, jd_text)
            if result:
                return result
            # analyze_job_description trả None nghĩa là đã tự log lỗi rồi
            # (vd JSON không cứu được) — không cần retry loại lỗi này, vì
            # gọi lại với cùng input nhiều khả năng ra kết quả tương tự.
            return None
        except Exception as e:
            if attempt <= retries:
                logger.warning(
                    f"  → lỗi tạm thời id={job_id} (lần {attempt}/{retries}), thử lại: {e}"
                )
                time.sleep(2.0 * attempt)  # backoff tăng dần
            else:
                logger.error(f"  → hết lượt retry id={job_id}: {e}")
    return None


async def run_analysis(limit: int | None = None, force_reindex: bool = False) -> dict:
    logger.info("=== Bắt đầu pipeline phân tích job ===")

    logger.info("Load CV index...")
    cv_index = get_cv_index(force_reindex=force_reindex)
    query_engine = setup_llm_and_query_engine(cv_index)

    jobs = await get_unanalyzed_jobs(limit=limit)
    stats = {"total": len(jobs), "ok": 0, "fail": 0, "skip": 0, "stopped_early": False}
    consecutive_failures = 0

    for i, row in enumerate(jobs, 1):
        job = dict(row)
        job_id = job["id"]
        title = job.get("job_title") or f"id={job_id}"
        logger.info(f"[{i}/{stats['total']}] Phân tích: {title}")

        try:
            jd_text = compose_job_text(job)
            if len(jd_text) < 40:
                logger.warning(f"  → skip (JD rỗng/ngắn) id={job_id}")
                stats["skip"] += 1
                consecutive_failures = 0  # skip không tính là lỗi hệ thống
                continue

            result = _analyze_with_retry(query_engine, jd_text, job_id, JOB_RETRY_COUNT)
            if not result:
                stats["fail"] += 1
                consecutive_failures += 1
            else:
                await update_job_with_analysis(
                    job_id,
                    result["match_score"],
                    result["ai_analysis"],
                )
                stats["ok"] += 1
                consecutive_failures = 0
        except Exception:
            # Bắt rộng ở đây (kể cả lỗi lưu DB) để 1 job lỗi bất ngờ không
            # làm dừng cả batch — job này coi như fail, các job sau vẫn chạy.
            logger.exception(f"  → lỗi không lường trước id={job_id}, bỏ qua job này")
            stats["fail"] += 1
            consecutive_failures += 1

        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.error(
                f"=== DỪNG SỚM: {consecutive_failures} job lỗi LIÊN TIẾP — "
                "nhiều khả năng Ollama đã chết/OOM, không phải lỗi JD đơn lẻ. "
                f"Còn {stats['total'] - i} job chưa phân tích, sẽ được lấy lại "
                "ở lần chạy tiếp theo (get_unanalyzed_jobs). Kiểm tra Ollama "
                "(`ollama ps`, log server) trước khi chạy lại. ==="
            )
            stats["stopped_early"] = True
            break

        if JOB_PACING_SECONDS > 0 and i < stats["total"]:
            time.sleep(JOB_PACING_SECONDS)

    logger.info(
        f"=== Xong: total={stats['total']} ok={stats['ok']} "
        f"fail={stats['fail']} skip={stats['skip']}"
        + (" (DỪNG SỚM)" if stats["stopped_early"] else "")
        + " ==="
    )
    await close_pool()
    return stats


def main():
    parser = argparse.ArgumentParser(description="Phân tích job vs CV bằng LLM local")
    parser.add_argument("--limit", type=int, default=None, help="Giới hạn số job (test)")
    parser.add_argument(
        "--force-reindex",
        action="store_true",
        help="Tạo lại CV index dù đã có",
    )
    args = parser.parse_args()
    asyncio.run(run_analysis(limit=args.limit, force_reindex=args.force_reindex))


if __name__ == "__main__":
    main()