"""
Entry point pipeline:
  python -m src.main --crawl ...
  python -m src.main --analyze [--limit N]
  python -m src.main --notify [--min-score N] [--dry-run]
  python -m src.main --crawl --analyze --notify
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_crawler(extra_args: list[str] | None = None) -> int:
    """Gọi scrapy crawl generic_job_spider với args tùy chọn."""
    crawler_dir = PROJECT_ROOT / "src" / "job_crawler"
    if not (crawler_dir / "scrapy.cfg").exists():
        # fallback layout cũ
        crawler_dir = PROJECT_ROOT / "job_crawler"

    cmd = ["scrapy", "crawl", "generic_job_spider"]
    if extra_args:
        cmd.extend(extra_args)

    logger.info(f"Chạy crawler: {' '.join(cmd)} (cwd={crawler_dir})")
    try:
        subprocess.run(cmd, cwd=str(crawler_dir), check=True)
        logger.info("Crawl xong.")
        return 0
    except FileNotFoundError:
        logger.error("Không tìm thấy lệnh scrapy. Hãy kích hoạt .venv.")
        return 1
    except subprocess.CalledProcessError as e:
        logger.error(f"Scrapy lỗi, code={e.returncode}")
        return e.returncode


def run_analyze(limit: int | None = None, force_reindex: bool = False) -> int:
    from src.analysis.run_analysis import run_analysis

    stats = asyncio.run(run_analysis(limit=limit, force_reindex=force_reindex))
    return 0 if stats.get("fail", 0) == 0 else 2


def run_notify(min_score: int, limit: int | None, dry_run: bool) -> int:
    from src.notification.run_notify import run_notify as _run_notify

    stats = asyncio.run(_run_notify(min_score=min_score, limit=limit, dry_run=dry_run))
    # sent=False chỉ là lỗi thật khi có job để gửi mà gửi thất bại; không
    # có job phù hợp (found=0) không phải lỗi.
    if stats.get("found", 0) > 0 and not dry_run and not stats.get("sent"):
        return 3
    return 0


def main():
    parser = argparse.ArgumentParser(description="AI Job Search & Analysis Pipeline")
    parser.add_argument("--crawl", action="store_true", help="Chạy Scrapy crawl")
    parser.add_argument("--analyze", action="store_true", help="Phân tích job chưa có score")
    parser.add_argument("--notify", action="store_true", help="Gửi email job phù hợp")
    parser.add_argument("--limit", type=int, default=None, help="Giới hạn số job khi analyze")
    parser.add_argument("--force-reindex", action="store_true", help="Tạo lại CV index")
    parser.add_argument(
        "--min-score", type=int,
        default=int(os.getenv("NOTIFY_MIN_SCORE", "70")),
        help="Ngưỡng match_score tối thiểu để đưa vào email (mặc định 70)",
    )
    parser.add_argument(
        "--notify-limit", type=int, default=None,
        help="Giới hạn số job trong email (mặc định không giới hạn)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Dùng với --notify: không gửi email thật, chỉ ghi ra dry_run_email.html",
    )
    # Proxy scrapy args: -a site_name=topcv -a keyword=...
    parser.add_argument("-a", action="append", dest="scrapy_a", default=[], help="Scrapy -a key=value")
    args = parser.parse_args()

    if not args.crawl and not args.analyze and not args.notify:
        parser.print_help()
        print("\nVí dụ:")
        print("  python -m src.main --crawl -a site_name=topcv -a keyword=ai-engineer -a location=ha-noi -a exp=1,2,3")
        print("  python -m src.main --analyze --limit 10")
        print("  python -m src.main --notify --min-score 75 --dry-run")
        print("  python -m src.main --crawl --analyze --notify -a site_name=topcv -a keyword=python")
        return

    code = 0
    if args.crawl:
        extra = []
        for item in args.scrapy_a:
            extra.extend(["-a", item])
        code = run_crawler(extra) or code

    if args.analyze:
        code = run_analyze(limit=args.limit, force_reindex=args.force_reindex) or code

    if args.notify:
        code = run_notify(
            min_score=args.min_score, limit=args.notify_limit, dry_run=args.dry_run
        ) or code

    sys.exit(code)


if __name__ == "__main__":
    main()